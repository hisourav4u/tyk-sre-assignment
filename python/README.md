# Tyk-SRE-Tool (Python)

Changes in this particular fork are about extending the solution for the SRE tool on Python.

### Run the python program as script
```
python3 -m venv .venv
source .venv/bin/activate
pip3 install -r requirements.txt
python main.py --kubeconfig ~/.kube/config --address 127.0.0.1:8080
```

### Scenarios covered

1. As an SRE I want to know whether all the deployments in the k8s cluster have as many healthy pods as requested by the respective `Deployment` spec:

```
curl http://127.0.0.1:8080/deployment-health
```

2. As an SRE I want to prevent two workloads defined by k8s namespace(s) and label selectors from being able to exchange any network activity on demand:

```
curl -X POST http://127.0.0.1:8080/block-traffic \
  -H "Content-Type: application/json" \
  -d '{
    "from_ns": "ns-1",
    "from_labels": {"app": "app1"},
    "to_ns": "ns-2",
    "to_labels": {"app": "app2"}
  }'
```

3. As an SRE I want to always know whether this tool can successfully communicate with the configured k8s API server:

```
curl http://127.0.0.1:8080/status

I changed the existing /healthz endpoint to /status as this sounds more meaningful.
This will return if its connected to the K8s API server and the version of the same.
```

4. As an application developer I want to build this application into a container image when I push a commit to the `main` branch of its repository:

```
A GHA workflow created under .github/workflows/deploy.yaml to build the image on push to main branch.
As an addon, I have also added a step to perform helm deployment, to test it out on my local minikube cluster, and it worked.
```

5. As an application developer I want to be able to deploy this application into a Kubernetes cluster using Helm:

```
Build the image using present Dockerfile

docker build -t tyk-sre-tool:latest .

Then, use Helm chart created under /python directory for deployment purpose. Proper permissions have been added as RBAC,
to make sure it has the required access to perform the needed operation on the cluster.

helm upgrade --install tyk-sre-tool ./helm-chart --namespace sre-tool --create-namespace --set image.tag=latest

One ingress has also been added to expose the service behind a domain (http://tyk-sre-tool.local/). 
So, after you've deployed it on cluster, you can access all the above mentioned endpoints through this domain.
```

Have added few more test cases to the existing tests.py file to cover the code changes that I made.
