# KubeSlice Multi-Cluster Kubernetes Deployment with Pulumi

This project uses Pulumi to automate the deployment of a KubeSlice environment on Linode Kubernetes Engine (LKE). It sets up a controller cluster and multiple worker clusters, enabling seamless multi-cluster network communication.

## Architecture Overview

The deployment consists of:
- One KubeSlice controller cluster
- Multiple worker clusters (configurable)
- Istio service mesh on each worker cluster
- Optional KubeSlice Enterprise components
- Sample Bookinfo application (frontend and backend) deployment across clusters when enabled

### Kubeslice Architecture Diagram

![image](https://github.com/user-attachments/assets/c997c547-4794-4531-ba60-3057a3fee9e9)


## Prerequisites

- [Pulumi CLI](https://www.pulumi.com/docs/get-started/install/)
- [Python 3.11+](https://www.python.org/downloads/)
- [Linode Account](https://www.linode.com/) and API Token
- [kubectl](https://kubernetes.io/docs/tasks/tools/install-kubectl/) (for cluster interaction)

## Getting Started

1. Clone this repository:
```bash
git clone <repository-url>
cd <repository-directory>
```

2. Create a Python virtual environment and install the required libraries:
> [!TIP]
> Configure a [local pulumi state](https://www.pulumi.com/docs/iac/concepts/state-and-backends/#local-filesystem) using `pulumi login --local` before executing any pulumi command
```bash
pulumi install
```

3. Modify the `config-file.yaml` with your desired configuration for the deployment:

```yaml
config:
  region_lke_controller: es-mad  # Region for controller cluster
  lke_version: "1.32" #global LKE version
  lke_controller_node_type: "g6-standard-1"
  lke_controller_node_count: 3

  # Worker clusters configuration
  worker_clusters:
    worker1:
      region: es-mad
      worker_node_type: g6-standard-2
      worker_node_count: 1
      gw_node_type: g6-standard-2
      gw_node_count: 2
      application_frontend: true
      application_backend: false
    worker2:
      region: fr-par
      worker_node_type: g6-standard-2
      worker_node_count: 1
      gw_node_type: g6-standard-2
      gw_node_count: 2
      application_frontend: false
      application_backend: true
    # worker3:
    #   region: it-mil
    #   worker_node_type: g6-standard-2
    #   worker_node_count: 1
    #   gw_node_type: g6-standard-2
    #   gw_node_count: 2
    #   application_frontend: true
    #   application_backend: false

  # Optional: Enterprise configuration
  kubeslice_enterprise:
    enabled: false
    username: ""
    password: ""
    email: ""
```

4. Set up your Linode token:
```bash
export LINODE_TOKEN=<your-token>
```

5. Preview the deployment:
> [!NOTE]
> You will be prompted to provide a stack name and secret storage password
```bash
pulumi preview --config-file=config-file.yaml
```

6. Deploy the infrastructure:
> [!NOTE]
> Re-exceute the command if any error occur during the deployment
```bash
pulumi up --config-file=config-file.yaml --skip-preview
```

The deployment process will:
1. Create the controller cluster
2. Install KubeSlice controller components
3. Create worker clusters
4. Install required components on worker clusters (Istio, Prometheus if enterprise)
5. Register worker clusters with the controller
6. Deploy the Bookinfo application across clusters

## Accessing the Clusters

After deployment, you can get the kubeconfig for each cluster in [Linode cloud manager](https://cloud.linode.com/):

```bash
# Access controller cluster (same for worker clusters)
export KUBECONFIG=controller-kubeconfig.yaml
kubectl get nodes
```

## Enterprise Features

To enable enterprise features:

1. Update your Pulumi config with enterprise credentials:
```yaml
kubeslice_enterprise:
  enabled: true
  username: "your-username"
  password: "your-password"
  email: "your-email"
```

2. Redeploy:
> [!NOTE]
> Delete and recreate the infrastructure if there is any error updating it
```bash
pulumi up --config-file=config-file.yaml --skip-preview
```

Enterprise deployment includes:
- Enterprise version of KubeSlice components
- KubeSlice UI
- Prometheus monitoring

## Cleanup

To destroy all created resources:
```bash
pulumi destroy
```

## Troubleshooting

Common issues and solutions:

1. **Cluster creation timeout**
   - Re-execute the command
   - Check Linode quota limits

2. **Worker registration fails**
   - Verify network connectivity between clusters
   - Check the name of the worker cluster is not longer than 15 characters
   - Review the component health of each cluster: `kubectl describe cluster <cluster-name> -n kubeslice-<project name>`

3. **Application deployment issues**
   - Verify namespace labels: `kubectl get ns bookinfo --show-labels`
   - Verify the ServiceExport/Import status is TRUE: `kubectl get serviceimport -n bookinfo`
   - Check pod status: `kubectl get pods -n bookinfo`
   - Review Istio sidecar injection: `kubectl describe pod -n bookinfo <pod-name>`
4. **Known deployment error**
   - Re-execute the command `pulumi up --config-file=config-file.yaml --skip-preview` when the following error occurs:
   ```
   Diagnostics:
    pulumi:pulumi:Stack (kubeslice-kubeslice):
      error: kubernetes:yaml/v2:ConfigGroup resource 'kubeslice-project' has a problem: marshaling properties: awaiting input property "resources": failed to determine if the following GVK is namespaced: controller.kubeslice.io/v1alpha1, Kind=Project

   ```
   This is a known pulumi bug: https://github.com/pulumi/pulumi-kubernetes/issues/3176


## Project Structure

```
.
├── Pulumi.yaml                 # Pulumi project file
├── config-file.yaml            # Stack configuration
├── __main__.py                # Main deployment code
├── requirements.txt           # Python dependencies
└── bookinfo-app/             # Application manifests
    ├── productpage.yaml
    ├── details.yaml
    ├── ratings.yaml
    ├── reviews.yaml
    └── servicesexport-*.yaml
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## Support

For support, please:
1. Check the [KubeSlice documentation](https://kubeslice.io/documentation/)
2. Open an issue in the repository
3. Contact Linode support for infrastructure-related issues

## License

This project is licensed under the MIT License - see the LICENSE file for details.
