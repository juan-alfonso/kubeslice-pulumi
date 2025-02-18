###############################################################################
# KubeSlice Infrastructure Deployment using Pulumi
# This script sets up a KubeSlice environment with controller and worker clusters
# on Linode Kubernetes Engine (LKE)
###############################################################################

# Configuration imports
import pulumi
import pulumi_linode as linode
import pulumi_kubernetes as k8s
import base64
import yaml
import pulumiverse_time as time

# Configuration section
# Read and set default values for cluster configuration including node types,
# counts, kubernetes version, and regional settings
config = pulumi.Config()
linode_token = config.require("linode_token")
lke_gw_node_type = config.get("lke_gw_node_type") or "g6-standard-2"
lke_worker_node_type = config.get("lke_worker_node_type") or "g6-standard-2"
lke_controller_node_type = config.get("lke_controller_node_type") or "g6-standard-1"
lke_gw_node_count = config.get_int("lke_gw_node_count") or 1
lke_worker_node_count = config.get_int("lke_worker_node_count") or 3
lke_controller_node_count = config.get_int("lke_controller_node_count") or 3
lke_version = config.get("lke_version") or "1.31"
region_lke_controller = config.require("region_lke_controller")
worker_clusters = config.require_object("worker_clusters")
project_name = "bookinfo-project"
namespaced_project_name = "kubeslice-bookinfo-project"
application_namespace="bookinfo"

# Enterprise version configuration
# Check if enterprise version is enabled and set appropriate helm repository and version
kubeslice_enterprise=config.get_object("kubeslice_enterprise")
enterprise_enabled = kubeslice_enterprise.get("enabled", False) if kubeslice_enterprise else False

if enterprise_enabled == True:
  enterprise_username=kubeslice_enterprise.get("username")
  enterprise_password=kubeslice_enterprise.get("password")
  enterprise_email=kubeslice_enterprise.get("email")
  helm_repository_kubeslice="https://kubeslice.aveshalabs.io/repository/kubeslice-helm-ent-prod/"
  helm_chart_version="1.15.0"
else:
  helm_repository_kubeslice="https://kubeslice.github.io/kubeslice/"
  helm_chart_version="1.3.1"

###############################################################################
# Controller Cluster Setup
###############################################################################

# Initialize Linode provider with authentication token
linode_provider = linode.Provider(
    "linode-provider",
    token=linode_token  # Pass the Linode token explicitly
)

# Create the KubeSlice controller LKE cluster
# This cluster will manage the worker clusters and slice configurations
controller_cluster = linode.LkeCluster(
    "kubeslice-controller",
    label="kubeslice-controller",
    k8s_version=lke_version,
    region=region_lke_controller,
    tags=["app:kubeslice-controller"],
    pools=[linode.LkeClusterPoolArgs(
        type=lke_controller_node_type,
        count=lke_controller_node_count,
    )]
)

# Decode the kubeconfig for the controller cluster
controller_kubeconfig = controller_cluster.kubeconfig.apply(
    lambda k: base64.b64decode(k).decode("utf-8")
)

# Create a Kubernetes provider for the controller cluster
controller_provider = k8s.Provider(
    "kubeslice-controller",
    kubeconfig=controller_kubeconfig, enable_server_side_apply=True
)


###############################################################################
# KubeSlice Controller Installation
###############################################################################

# Prepare values for KubeSlice controller installation
# Different configurations for enterprise and community editions
if enterprise_enabled:
  kubeslice_controller_values = controller_kubeconfig.apply(lambda kubeconfig: {
      "kubeslice": {
          "controller": {
              "endpoint": yaml.safe_load(kubeconfig)["clusters"][0]["cluster"]["server"]
          },
          "license": {
             "type": "kubeslice-trial-license",
             "mode": "auto",
             "customerName": enterprise_email
          }          
      },
      "imagePullSecrets": {
             "username": enterprise_username,
             "password": enterprise_password,
             "email": enterprise_email
          }
  })

  kubeslice_ui_values = {
      "imagePullSecrets": {
            "username": enterprise_username,
            "password": enterprise_password,
            "email": enterprise_email
          }
  }
else:
  kubeslice_controller_values = controller_kubeconfig.apply(lambda kubeconfig: {
      "kubeslice": {
          "controller": {
              "endpoint": yaml.safe_load(kubeconfig)["clusters"][0]["cluster"]["server"]
          }
      }
  })

#Create kubeslice-controller namespace
namespace_kubeslice_controller = k8s.core.v1.Namespace(
    "kubeslice-controller",
    metadata={
        "name": "kubeslice-controller",
    },
    opts=pulumi.ResourceOptions(provider=controller_provider)
)

# Install kubeslice-controller
kubeslice_controller_release = k8s.helm.v3.Release("kubeslice-controller",
    chart="kubeslice-controller",
    namespace="kubeslice-controller",
    repository_opts=k8s.helm.v3.RepositoryOptsArgs(
        repo=helm_repository_kubeslice,
    ),
    version=helm_chart_version,
    values=kubeslice_controller_values,
    skip_await=False,
    opts=pulumi.ResourceOptions(
        provider=controller_provider,
        depends_on=[namespace_kubeslice_controller],
        ignore_changes=["*"]))

# Install kubeslice-controller if enterprise enabled
if enterprise_enabled:
  kubeslice_ui_release = k8s.helm.v3.Release("kubeslice-ui",
      chart="kubeslice-ui",
      namespace="kubeslice-controller",
      repository_opts=k8s.helm.v3.RepositoryOptsArgs(
          repo=helm_repository_kubeslice,
      ),
      version=helm_chart_version,
      values=kubeslice_ui_values,
      skip_await=False,
      opts=pulumi.ResourceOptions(
          provider=controller_provider,
          depends_on=[namespace_kubeslice_controller],
          ignore_changes=["*"]))

# Introduce a 30-second delay
wait30_seconds = time.Sleep("wait30Seconds", create_duration="30s", opts = pulumi.ResourceOptions(depends_on=[kubeslice_controller_release]))


#Create kubeslice controller project
kubeslice_project_raw_yaml=f"""
apiVersion: controller.kubeslice.io/v1alpha1
kind: Project
metadata:
  name: {project_name}
  namespace: kubeslice-controller
spec:
  serviceAccount:
    readOnly:
    - readonly-user1
    - readonly-user2
    readWrite:
    - readwrite-user1
    - readwrite-user2
"""

kubeslice_project =k8s.yaml.v2.ConfigGroup(
    "kubeslice-project",
    objs=[yaml.safe_load(kubeslice_project_raw_yaml)],
    opts=pulumi.ResourceOptions(
        provider=controller_provider,
        depends_on=[kubeslice_controller_release, wait30_seconds])
)


###############################################################################
# Worker Clusters Setup
###############################################################################

# Create worker clusters based on configuration
worker_clusters_resources = {}
worker_providers = {}

for cluster_name, cluster_config in worker_clusters.items():
    worker_cluster = linode.LkeCluster(
        f"kubeslice-{cluster_name}",
        label=f"kubeslice-{cluster_name}",
        k8s_version=lke_version,
        region=cluster_config["region"],
        tags=["app:kubeslice-worker"],
        control_plane=linode.LkeClusterControlPlaneArgs(
            high_availability=True
        ),
        pools=[
            # Worker node pool
            linode.LkeClusterPoolArgs(
                type=cluster_config["worker_node_type"],
                count=cluster_config["worker_node_count"],
            ),
            # Gateway node pool
            linode.LkeClusterPoolArgs(
                type=cluster_config["gw_node_type"],
                count=cluster_config["gw_node_count"],
                labels={"kubeslice.io/node-type": "gateway"},
            ),
        ]
    )
    worker_clusters_resources[cluster_name] = worker_cluster

    # Decode the kubeconfig for the worker cluster
    worker_kubeconfig = worker_cluster.kubeconfig.apply(
        lambda k: base64.b64decode(k).decode("utf-8")
    )

    # Create a Kubernetes provider for the worker cluster
    worker_provider = k8s.Provider(
        f"worker-provider-{cluster_name}",
        kubeconfig=worker_kubeconfig,
        enable_server_side_apply=True
    )
    worker_providers[cluster_name] = worker_provider

###############################################################################
# Worker Cluster Resource Creation
###############################################################################

# Helm releases and Kubernetes resources for worker clusters
def create_resources_for_worker(cluster_name, worker_provider):
    # Install required components:
    # 1. Istio base and discovery
    # 2. Prometheus (enterprise only)
    # 3. KubeSlice worker components

    # Install Istio
    istio_base_release = k8s.helm.v3.Release(
        f"istio-base-{cluster_name}",
        chart="istio-base",
        repository_opts=k8s.helm.v3.RepositoryOptsArgs(
            repo=helm_repository_kubeslice
        ),
        namespace="istio-system",
        create_namespace=True,
        opts=pulumi.ResourceOptions(provider=worker_provider)
    )

    istio_d_release = k8s.helm.v3.Release(
        f"istio-d-{cluster_name}",
        chart="istio-discovery",
        repository_opts=k8s.helm.v3.RepositoryOptsArgs(
            repo=helm_repository_kubeslice
        ),
        namespace="istio-system",
        opts=pulumi.ResourceOptions(
            provider=worker_provider,
            depends_on=[istio_base_release]
        )
    )

    # Install Prometheus if kubeslice enterprise enabled
    if kubeslice_enterprise:
      prometehus_release = k8s.helm.v3.Release(
        f"prometheus-{cluster_name}",
        chart="prometheus",
        repository_opts=k8s.helm.v3.RepositoryOptsArgs(
            repo=helm_repository_kubeslice
        ),
        namespace="monitoring",
        create_namespace=True,
        opts=pulumi.ResourceOptions(provider=worker_provider)
      )

    # Kubeslice Worker HelmRelease
    if kubeslice_enterprise:
       kubeslice_worker_values = pulumi.Output.all(
          controller_kubeconfig,
          worker_clusters_resources[cluster_name].kubeconfig
        ).apply(lambda args: {
            "controllerSecret": {
                "namespace": base64.b64encode(namespaced_project_name.encode()).decode(),
                "endpoint": base64.b64encode(yaml.safe_load(args[0])["clusters"][0]["cluster"]["server"].encode()).decode(),
                "ca.crt": yaml.safe_load(args[0])["clusters"][0]["cluster"]["certificate-authority-data"],
                "token": base64.b64encode(yaml.safe_load(args[0])["users"][0]["user"]["token"].encode()).decode(),
            },
            "cluster": {
                "name": f"kubeslice-{cluster_name}",  # Correctly capture the current cluster_name
                "endpoint": yaml.safe_load(base64.b64decode(args[1]).decode())["clusters"][0]["cluster"]["server"],
            },
            "netop": {
                "networkInterface": "eth0",
            },
            "imagePullSecrets": {
                "username": enterprise_username,
                "password": enterprise_password,
                "email": enterprise_email
              },
            "kubesliceNetworking": {
                "enabled": True,
            },
            "metrics": {
                "insecure": True,
            }
        })
       
    else:
      kubeslice_worker_values = pulumi.Output.all(
          controller_kubeconfig,
          worker_clusters_resources[cluster_name].kubeconfig
        ).apply(lambda args: {
            "controllerSecret": {
                "namespace": base64.b64encode(namespaced_project_name.encode()).decode(),
                "endpoint": base64.b64encode(yaml.safe_load(args[0])["clusters"][0]["cluster"]["server"].encode()).decode(),
                "ca.crt": yaml.safe_load(args[0])["clusters"][0]["cluster"]["certificate-authority-data"],
                "token": base64.b64encode(yaml.safe_load(args[0])["users"][0]["user"]["token"].encode()).decode(),
            },
            "cluster": {
                "name": f"kubeslice-{cluster_name}",  # Correctly capture the current cluster_name
                "endpoint": yaml.safe_load(base64.b64decode(args[1]).decode())["clusters"][0]["cluster"]["server"],
            },
            "netop": {
                "networkInterface": "eth0",
            }
        })

    kubeslice_worker_release=k8s.helm.v3.Release(
        f"kubeslice-{cluster_name}",
        chart="kubeslice-worker",
        repository_opts=k8s.helm.v3.RepositoryOptsArgs(
            repo=helm_repository_kubeslice
        ),
        version=helm_chart_version,
        namespace="kubeslice-system",
        values=kubeslice_worker_values,
        create_namespace=True,
        opts=pulumi.ResourceOptions(
            provider=worker_provider,
            depends_on=[istio_d_release]
        )
    )

    return kubeslice_worker_release

# Loop through worker clusters and create resources
for cluster_name, worker_provider in worker_providers.items():
    kubeslice_worker_release=create_resources_for_worker(cluster_name, worker_provider)


###############################################################################
# Worker cluster registrations on controller
###############################################################################
cluster_registration_status=[]

for cluster_name in worker_clusters.keys():

    # Introduce a 15-second delay
    wait15_seconds_project = time.Sleep(f"wait15Seconds_project_{cluster_name}", create_duration="15s", opts = pulumi.ResourceOptions(depends_on=[kubeslice_project]))
    
    worker_cluster_registration_raw_yaml=f"""
    apiVersion: controller.kubeslice.io/v1alpha1
    kind: Cluster
    metadata:
      name: kubeslice-{cluster_name}
      namespace: {namespaced_project_name}
      annotations:
        pulumi.com/waitFor: "jsonpath={{.status.clusterHealth.clusterHealthStatus}}=Normal"
    spec:
      networkInterface: eth0
      clusterProperty:
        geoLocation:
          cloudProvider: "linode"
          cloudRegion: "{worker_clusters[cluster_name]['region']}"
    """
    worker_cluster_registration=k8s.yaml.v2.ConfigGroup(
        f"registration-{cluster_name}",
        yaml=worker_cluster_registration_raw_yaml,
        opts=pulumi.ResourceOptions(
            provider=controller_provider,
            depends_on=[kubeslice_project, wait15_seconds_project])
    )

    cluster_registration_status.append(worker_cluster_registration)


###############################################################################
# Create slice_config for all registered clusters
###############################################################################

def create_slice_config(namespaced_project_name , application_namespace, worker_clusters):

    cluster_names = [f"kubeslice-{cluster_name}" for cluster_name in worker_clusters.keys()]
    # Correctly format the cluster names as a YAML list of strings
    indented_clusters = "\n".join([f"  - {cluster}" for cluster in cluster_names])

    slice_config_raw_yaml=f"""
apiVersion: controller.kubeslice.io/v1alpha1
kind: SliceConfig
metadata:
  name: slice-{application_namespace}
  namespace: {namespaced_project_name}
spec:
  sliceSubnet: 10.11.0.0/16
  maxClusters: 10
  sliceType: Application
  sliceGatewayProvider:
    sliceGatewayType: OpenVPN
    sliceCaType: Local
  sliceIpamType: Local
  clusters:
{indented_clusters}
  qosProfileDetails:
    queueType: HTB
    priority: 1
    tcType: BANDWIDTH_CONTROL
    bandwidthCeilingKbps: 5120
    bandwidthGuaranteedKbps: 2560
    dscpClass: AF11
  namespaceIsolationProfile:
    applicationNamespaces:
    - namespace: {application_namespace}
      clusters:
      - '*'
    isolationEnabled: false
    """

    return slice_config_raw_yaml


slice_config = create_slice_config(namespaced_project_name, application_namespace, worker_clusters)

kubeslice_slice_config =k8s.yaml.v2.ConfigGroup(
    "kubeslice-slice-config",
    objs=[yaml.safe_load(slice_config)],
    opts=pulumi.ResourceOptions(
        provider=controller_provider,
        depends_on=[*cluster_registration_status, kubeslice_worker_release])
)

###############################################################################
# Application Deployment
###############################################################################

# Deploy YAML manifests based on application_frontend and application_backend flags
def deploy_application(worker_provider, application_namespace, cluster_name):
    resources = []

    cluster_config = worker_clusters.get(cluster_name, {})
    frontend_enabled = cluster_config.get("application_frontend", False)
    backend_enabled = cluster_config.get("application_backend", False)

    #Create application namespace with istio enabled
    namespace_application = k8s.core.v1.Namespace(
        f"namespace-application-{cluster_name}",
        metadata={
            "name": f"{application_namespace}",
            "labels": {
              "istio-injection": "enabled"
          }
        },
        opts=pulumi.ResourceOptions(provider=worker_provider)
    )

    # Introduce a 30-second delay to wait for namespace kubeslice labels to inject the sidecards
    wait30_seconds_sidecars = time.Sleep(f"wait30Seconds_sidecars_{cluster_name}", create_duration="30s", opts = pulumi.ResourceOptions(depends_on=[kubeslice_slice_config]))

    if frontend_enabled:
        frontend_manifest = k8s.yaml.v2.ConfigGroup(
            f"frontend-manifest-{cluster_name}-{application_namespace}",
            files=["./bookinfo-app/productpage.yaml"],
            opts=pulumi.ResourceOptions(
                provider=worker_provider,
                depends_on=[kubeslice_slice_config, kubeslice_worker_release, wait30_seconds_sidecars])
        )
        resources.append(frontend_manifest)

    if backend_enabled:
        backend_manifest = k8s.yaml.v2.ConfigGroup(
            f"backend-manifest-{cluster_name}-{application_namespace}",
            files=["./bookinfo-app/ratings.yaml","./bookinfo-app/details.yaml","./bookinfo-app/reviews.yaml","./bookinfo-app/servicesexport-details.yaml","./bookinfo-app/servicesexport-reviews.yaml"],
            opts=pulumi.ResourceOptions(
                provider=worker_provider,
                depends_on=[kubeslice_slice_config, kubeslice_worker_release, wait30_seconds_sidecars]
            )
        )
        resources.append(backend_manifest)

    return resources

# Loop through worker clusters and create resources
for cluster_name, worker_provider in worker_providers.items():
    deploy_application(worker_provider, application_namespace, cluster_name)