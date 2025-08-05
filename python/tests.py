import unittest
import socket
import requests

from unittest.mock import MagicMock
from socketserver import TCPServer
from threading import Thread
from kubernetes import client
from kubernetes.client.models import VersionInfo

from app import app


class TestGetKubernetesVersion(unittest.TestCase):
    def test_good_version(self):
        api_client = client.ApiClient()

        version = VersionInfo(
            build_date="",
            compiler="",
            git_commit="",
            git_tree_state="fake",
            git_version="1.25.0-fake",
            go_version="",
            major="1",
            minor="25",
            platform=""
        )
        api_client.call_api = MagicMock(return_value=version)

        version = app.get_kubernetes_version(api_client)
        self.assertEqual(version, "1.25.0-fake")

    def test_exception(self):
        api_client = client.ApiClient()
        api_client.call_api = MagicMock(side_effect=ValueError("test"))

        with self.assertRaisesRegex(ValueError, "test"):
            app.get_kubernetes_version(api_client)


class TestAppHandler(unittest.TestCase):
    def setUp(self):
        super().setUp()

        port = self._get_free_port()
        self.mock_server = TCPServer(("localhost", port), app.AppHandler)

        # Run the mock TCP server with AppHandler on a separate thread to avoid blocking the tests.
        self.mock_server_thread = Thread(target=self.mock_server.serve_forever)
        self.mock_server_thread.daemon = True
        self.mock_server_thread.start()

    def tearDown(self):
        self.mock_server.shutdown()
        self.mock_server.server_close()

    def _get_free_port(self):
        """Returns a free port number from OS"""
        s = socket.socket(socket.AF_INET, type=socket.SOCK_STREAM)
        s.bind(("localhost", 0))
        __, port = s.getsockname()
        s.close()

        return port

    def _get_url(self, target):
        """Returns a URL to pass into the requests so that they reach this suite's mock server"""
        host, port = self.mock_server.server_address
        return f"http://{host}:{port}/{target}"

    def test_status_ok(self):
        resp = requests.get(self._get_url("status"))
        self.assertEqual(resp.status_code, 200)

        data = resp.json()
        self.assertIn("connected to K8s API Server", data)
        self.assertIn("kubernetes_version", data)

        # connected should be True (assuming kubeconfig is valid and cluster is reachable)
        self.assertIsInstance(data["connected to K8s API Server"], bool)
        self.assertIsInstance(data["kubernetes_version"], str)


    def test_deployment_health(self):
        # Patch AppsV1Api.list_deployment_for_all_namespaces to return mocked data
        mock_deployment = MagicMock()
        mock_deployment.spec.replicas = 3
        mock_deployment.status.available_replicas = 2
        mock_deployment.metadata.name = "app1"
        mock_deployment.metadata.namespace = "ns1"

        app.client.AppsV1Api.list_deployment_for_all_namespaces = MagicMock(
            return_value=MagicMock(items=[mock_deployment])
        )

        resp = requests.get(self._get_url("deployment-health"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("unhealthy_deployments", resp.json())
        self.assertEqual(len(resp.json()["unhealthy_deployments"]), 1)

    def test_block_traffic(self):
        # Patch the Kubernetes API call to prevent real cluster interaction
        app.client.NetworkingV1Api.create_namespaced_network_policy = MagicMock(return_value=None)

        payload = {
            "from_ns": "ns-1",
            "from_labels": {"app": "app1"},
            "to_ns": "ns-2",
            "to_labels": {"app": "app2"}
        }

        resp = requests.post(self._get_url("block-traffic"), json=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "policy_created"})


if __name__ == '__main__':
    unittest.main()
