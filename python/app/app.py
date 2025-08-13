import json
import socketserver
from kubernetes import client
from http.server import BaseHTTPRequestHandler

class AppHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        """Catch all incoming GET requests"""
        if self.path == "/status":
            self.status()
        elif self.path == "/deployment-health":
            self.deployment_health()
        elif self.path == "/list-blocks":
            blocks = list_traffic_blocks()
            self.respond(200, json.dumps({"blocks": blocks}))
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/block-traffic":
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)

            from_ns = data["from_ns"]
            from_labels = data["from_labels"]
            to_ns = data["to_ns"]
            to_labels = data["to_labels"]

            block_traffic(from_ns, from_labels, to_ns, to_labels)
            self.respond(200, json.dumps({"status": "policy_created"}))

        elif self.path == "/unblock-traffic":
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)

            from_ns = data["from_ns"]
            from_labels = data["from_labels"]
            to_ns = data["to_ns"]
            to_labels = data["to_labels"]

            result = unblock_traffic(from_ns, from_labels, to_ns, to_labels)
            self.respond(200, json.dumps(result))

        else:
            self.send_error(404)

    def status(self):
        try:
            version = get_kubernetes_version(client.ApiClient())
            response = {
                "connected to K8s API Server": True,
                "kubernetes_version": version
            }
            self.respond(200, json.dumps(response))
        except Exception as e:
            response = {
                "connected to K8s API Server": False,
                "error": str(e)
            }
            self.respond(500, json.dumps(response))


    def deployment_health(self):
        apps_v1 = client.AppsV1Api()
        ret = apps_v1.list_deployment_for_all_namespaces()
        unhealthy = []
        for dep in ret.items:
            desired = dep.spec.replicas
            available = dep.status.available_replicas or 0
            if desired != available:
                unhealthy.append({"name": dep.metadata.name, "namespace": dep.metadata.namespace,
                                  "desired": desired, "available": available})
        self.respond(200, json.dumps({"unhealthy_deployments": unhealthy}))

    def respond(self, status: int, content: str):
        """Writes content and status code to the response socket"""
        self.send_response(status)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()

        self.wfile.write(bytes(content, "UTF-8"))


def get_kubernetes_version(api_client: client.ApiClient) -> str:
    """
    Returns a string GitVersion of the Kubernetes server defined by the api_client.

    If it can't connect an underlying exception will be thrown.
    """
    version = client.VersionApi(api_client).get_code()
    return version.git_version


def start_server(address):
    """
    Launches an HTTP server with handlers defined by AppHandler class and blocks until it's terminated.

    Expects an address in the format of `host:port` to bind to.

    Throws an underlying exception in case of error.
    """
    try:
        host, port = address.split(":")
    except ValueError:
        print("invalid server address format")
        return

    with socketserver.TCPServer((host, int(port)), AppHandler) as httpd:
        print("Server listening on {}".format(address))
        httpd.serve_forever()

def block_traffic(from_ns, from_labels, to_ns, to_labels):
    """
    Creates network policies to block traffic between two sets of workloads.
    from_ns: Namespace of the source workloads.
    from_labels: Labels of the source workloads.
    to_ns: Namespace of the destination workloads.
    to_labels: Labels of the destination workloads.

    """
    networking_v1 = client.NetworkingV1Api()

    np1 = client.V1NetworkPolicy(
        metadata=client.V1ObjectMeta(
            name="block-{}-to-{}".format(from_labels["app"], to_labels["app"]),
            namespace=from_ns),
        spec=client.V1NetworkPolicySpec(
            pod_selector=client.V1LabelSelector(match_labels=from_labels),
            policy_types=["Egress"],
            egress=[client.V1NetworkPolicyEgressRule(
                to=[client.V1NetworkPolicyPeer(
                    namespace_selector=client.V1LabelSelector(
                        match_expressions=[client.V1LabelSelectorRequirement(
                            key="namespace", operator="NotIn", values=[to_ns])]),
                    pod_selector=client.V1LabelSelector(
                        match_expressions=[client.V1LabelSelectorRequirement(
                            key="app", operator="NotIn", values=[to_labels["app"]])])
                )]
            )]
        )
    )

    np2 = client.V1NetworkPolicy(
        metadata=client.V1ObjectMeta(
            name="block-{}-to-{}".format(to_labels["app"], from_labels["app"]),
            namespace=to_ns),
        spec=client.V1NetworkPolicySpec(
            pod_selector=client.V1LabelSelector(match_labels=to_labels),
            policy_types=["Egress"],
            egress=[client.V1NetworkPolicyEgressRule(
                to=[client.V1NetworkPolicyPeer(
                    namespace_selector=client.V1LabelSelector(
                        match_expressions=[client.V1LabelSelectorRequirement(
                            key="namespace", operator="NotIn", values=[from_ns])]),
                    pod_selector=client.V1LabelSelector(
                        match_expressions=[client.V1LabelSelectorRequirement(
                            key="app", operator="NotIn", values=[from_labels["app"]])])
                )]
            )]
        )
    )

    networking_v1.create_namespaced_network_policy(namespace=from_ns, body=np1)
    networking_v1.create_namespaced_network_policy(namespace=to_ns, body=np2)
    
def unblock_traffic(from_ns, from_labels, to_ns, to_labels):
    """
    Deletes the network policies created by block_traffic().
    """
    networking_v1 = client.NetworkingV1Api()

    policy1 = f"block-{from_labels['app']}-to-{to_labels['app']}"
    policy2 = f"block-{to_labels['app']}-to-{from_labels['app']}"

    results = {}

    for ns, name in [(from_ns, policy1), (to_ns, policy2)]:
        try:
            networking_v1.delete_namespaced_network_policy(
                name=name,
                namespace=ns
            )
            results[name] = "deleted"
        except ApiException as e:
            if e.status == 404:
                results[name] = "not_found"
            else:
                results[name] = f"error: {e.reason}"

    return results

def list_traffic_blocks():
    """
    Lists all active block traffic policies created by block_traffic().
    Returns a list of dicts with namespace and policy name.
    """
    networking_v1 = client.NetworkingV1Api()
    all_policies = networking_v1.list_network_policy_for_all_namespaces()
    
    blocks = []
    for policy in all_policies.items:
        if policy.metadata.name.startswith("block-"):
            blocks.append({
                "namespace": policy.metadata.namespace,
                "name": policy.metadata.name
            })
    
    return blocks
