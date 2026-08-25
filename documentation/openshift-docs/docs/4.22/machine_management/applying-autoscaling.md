Apply autoscaling to an OpenShift Container Platform cluster to automatically adjust the size of the cluster to meet deployment needs. You can deploy a cluster autoscaler and then deploy machine autoscalers for each machine type in your cluster. After you configure the cluster autoscaler, you must configure at least one machine autoscaler.

> [!IMPORTANT]
> You can configure the cluster autoscaler only in clusters where the Machine API Operator is operational.

# About the cluster autoscaler

The cluster autoscaler adjusts the size of an OpenShift Container Platform cluster to meet its current deployment needs. It uses declarative, Kubernetes-style arguments to provide infrastructure management that does not rely on objects of a specific cloud provider. The cluster autoscaler has a cluster scope, and is not associated with a particular namespace.

The cluster autoscaler increases the size of the cluster when there are pods that fail to schedule on any of the current worker nodes due to insufficient resources or when another node is necessary to meet deployment needs. The cluster autoscaler does not increase the cluster resources beyond the limits that you specify.

The cluster autoscaler computes the total memory, CPU, and GPU on all nodes the cluster, even though it does not manage the control plane nodes. These values are not single-machine oriented. They are an aggregation of all the resources in the entire cluster. For example, if you set the maximum memory resource limit, the cluster autoscaler includes all the nodes in the cluster when calculating the current memory usage. That calculation is then used to determine if the cluster autoscaler has the capacity to add more worker resources.

> [!IMPORTANT]
> Ensure that the `maxNodesTotal` value in the `ClusterAutoscaler` custom resource (CR) that you create is large enough to account for the total possible number of machines in your cluster. This value must encompass the number of control plane machines and the possible number of compute machines that you might scale to.

## Automatic node removal

Every 10 seconds, the cluster autoscaler checks which nodes are unnecessary in the cluster and removes them. The cluster autoscaler considers a node for removal if the following conditions apply:

- The node utilization is less than the *node utilization level* threshold for the cluster. The node utilization level is the sum of the requested resources divided by the allocated resources for the node. If you do not specify a value in the `ClusterAutoscaler` custom resource, the cluster autoscaler uses a default value of `0.5`, which corresponds to 50% utilization.

- The cluster autoscaler can move all pods running on the node to the other nodes. The Kubernetes scheduler is responsible for scheduling pods on the nodes.

- The cluster autoscaler does not have scale down disabled annotation.

If the following types of pods are present on a node, the cluster autoscaler will not remove the node:

- Pods with restrictive pod disruption budgets (PDBs).

- Kube-system pods that do not run on the node by default.

- Kube-system pods that do not have a PDB or have a PDB that is too restrictive.

- Pods that are not backed by a controller object such as a deployment, replica set, or stateful set.

- Pods with local storage.

- Pods that cannot be moved elsewhere because of a lack of resources, incompatible node selectors or affinity, matching anti-affinity, and so on.

- Unless they also have a `"cluster-autoscaler.kubernetes.io/safe-to-evict": "true"` annotation, pods that have a `"cluster-autoscaler.kubernetes.io/safe-to-evict": "false"` annotation.

For example, you set the maximum CPU limit to 64 cores and configure the cluster autoscaler to only create machines that have 8 cores each. If your cluster starts with 30 cores, the cluster autoscaler can add up to 4 more nodes with 32 cores, for a total of 62.

> [!NOTE]
> By default, when the cluster autoscaler removes a node, it does not cordon the node when draining the pods from the node. You can configure the cluster autoscaler to cordon the node before draining and moving the pods by setting the `spec.scaleDown.cordonNodeBeforeTerminating` parameter to `enabled` in the `ClusterAutoscaler` CR. This parameter is disabled by default. It is recommended to enable this parameter in production clusters because of the risk of data loss, application errors, pods getting stuck in the terminating state, or other issues if the cluster autoscaler removes a node when the parameter is disabled. Leaving this parameter disabled, which can result in faster node removal, might be appropriate in clusters that run only stateless workloads.

## Limitations

If you configure the cluster autoscaler, additional usage restrictions apply:

- Do not modify the nodes that are in autoscaled node groups directly. All nodes within the same node group have the same capacity and labels and run the same system pods.

- Specify requests for your pods.

- If you have to prevent pods from being deleted too quickly, configure appropriate PDBs.

- Confirm that your cloud provider quota is large enough to support the maximum node pools that you configure.

- Do not run additional node group autoscalers, especially the ones offered by your cloud provider.

> [!NOTE]
> The cluster autoscaler only adds nodes in autoscaled node groups if doing so would result in a schedulable pod. If the available node types cannot meet the requirements for a pod request, or if the node groups that could meet these requirements are at their maximum size, the cluster autoscaler cannot scale up.

## Interaction with other scheduling features

The horizontal pod autoscaler (HPA) and the cluster autoscaler modify cluster resources in different ways. The HPA changes the deployment’s or replica set’s number of replicas based on the current CPU load. If the load increases, the HPA creates new replicas, regardless of the amount of resources available to the cluster. If there are not enough resources, the cluster autoscaler adds resources so that the HPA-created pods can run. If the load decreases, the HPA stops some replicas. If this action causes some nodes to be underutilized or completely empty, the cluster autoscaler deletes the unnecessary nodes.

The cluster autoscaler takes pod priorities into account. The Pod Priority and Preemption feature enables scheduling pods based on priorities if the cluster does not have enough resources, but the cluster autoscaler ensures that the cluster has resources to run all pods. To honor the intention of both features, the cluster autoscaler includes a priority cutoff function. You can use this cutoff to schedule "best-effort" pods, which do not cause the cluster autoscaler to increase resources but instead run only when spare resources are available.

Pods with priority lower than the cutoff value do not cause the cluster to scale up or prevent the cluster from scaling down. No new nodes are added to run the pods, and nodes running these pods might be deleted to free resources.

## Cluster autoscaler resource definition

This `ClusterAutoscaler` resource definition shows the parameters and sample values for the cluster autoscaler.

> [!NOTE]
> When you change the configuration of an existing cluster autoscaler, it restarts.

``` yaml
apiVersion: "autoscaling.openshift.io/v1"
kind: "ClusterAutoscaler"
metadata:
  name: "default"
spec:
  podPriorityThreshold: -10
  resourceLimits:
    maxNodesTotal: 24
    cores:
      min: 8
      max: 128
    memory:
      min: 4
      max: 256
    gpus:
    - type: <gpu_type>
      min: 0
      max: 16
  logVerbosity: 4
  scaleDown:
    cordonNodeBeforeTerminating: Enabled
    enabled: true
    delayAfterAdd: 10m
    delayAfterDelete: 5m
    delayAfterFailure: 30s
    unneededTime: 5m
    utilizationThreshold: "0.4"
  scaleUp:
    newPodScaleUpDelay: "10s"
  expanders: ["Random"]
```

<table>
<caption>Cluster autoscaler parameters</caption>
<colgroup>
<col style="width: 25%" />
<col style="width: 75%" />
</colgroup>
<thead>
<tr>
<th style="text-align: left;">Parameter</th>
<th style="text-align: left;">Description</th>
</tr>
</thead>
<tbody>
<tr>
<td style="text-align: left;"><p><code>podPriorityThreshold</code></p></td>
<td style="text-align: left;"><p>Specify the priority that a pod must exceed to cause the cluster autoscaler to deploy additional nodes. Enter a 32-bit integer value. The <code>podPriorityThreshold</code> value is compared to the value of the <code>PriorityClass</code> that you assign to each pod.</p></td>
</tr>
<tr>
<td style="text-align: left;"><p><code>maxNodesTotal</code></p></td>
<td style="text-align: left;"><p>Specify the maximum number of nodes to deploy. This value is the total number of machines that are deployed in your cluster, not just the ones that the autoscaler controls. Ensure that this value is large enough to account for all of your control plane and compute machines and the total number of replicas that you specify in your <code>MachineAutoscaler</code> resources.</p></td>
</tr>
<tr>
<td style="text-align: left;"><p><code>cores.min</code></p></td>
<td style="text-align: left;"><p>Specify the minimum number of cores to deploy in the cluster.</p></td>
</tr>
<tr>
<td style="text-align: left;"><p><code>cores.max</code></p></td>
<td style="text-align: left;"><p>Specify the maximum number of cores to deploy in the cluster.</p></td>
</tr>
<tr>
<td style="text-align: left;"><p><code>memory.min</code></p></td>
<td style="text-align: left;"><p>Specify the minimum amount of memory, in GiB, in the cluster.</p></td>
</tr>
<tr>
<td style="text-align: left;"><p><code>memory.max</code></p></td>
<td style="text-align: left;"><p>Specify the maximum amount of memory, in GiB, in the cluster.</p></td>
</tr>
<tr>
<td style="text-align: left;"><p><code>gpus.type</code></p></td>
<td style="text-align: left;"><p>Optional: To configure the cluster autoscaler to deploy GPU-enabled nodes, specify a <code>type</code> value. This value must match the value of the <code>spec.template.spec.metadata.labels[cluster-api/accelerator]</code> label in the machine set that manages the GPU-enabled nodes of that type. For example, this value might be <code>nvidia-t4</code> to represent Nvidia T4 GPUs, or <code>nvidia-a10g</code> for A10G GPUs. For more information, see "Labeling GPU machine sets for the cluster autoscaler".</p></td>
</tr>
<tr>
<td style="text-align: left;"><p><code>gpus.min</code></p></td>
<td style="text-align: left;"><p>Specify the minimum number of GPUs of the specified type to deploy in the cluster.</p></td>
</tr>
<tr>
<td style="text-align: left;"><p><code>gpus.max</code></p></td>
<td style="text-align: left;"><p>Specify the maximum number of GPUs of the specified type to deploy in the cluster.</p></td>
</tr>
<tr>
<td style="text-align: left;"><p><code>logVerbosity</code></p></td>
<td style="text-align: left;"><p>Specify the logging verbosity level between <code>0</code> and <code>10</code>. The following log level thresholds are provided for guidance:</p>
<ul>
<li><p><code>1</code>: (Default) Basic information about changes.</p></li>
<li><p><code>4</code>: Debug-level verbosity for troubleshooting typical issues.</p></li>
<li><p><code>9</code>: Extensive, protocol-level debugging information.</p></li>
</ul>
<p>If you do not specify a value, the default value of <code>1</code> is used.</p></td>
</tr>
<tr>
<td style="text-align: left;"><p><code>scaleDown</code></p></td>
<td style="text-align: left;"><p>In this section, you can specify the period to wait for each action by using any valid <a href="https://golang.org/pkg/time/#ParseDuration">ParseDuration</a> interval, including <code>ns</code>, <code>us</code>, <code>ms</code>, <code>s</code>, <code>m</code>, and <code>h</code>.</p></td>
</tr>
<tr>
<td style="text-align: left;"><p><code>scaleDown.cordonNodeBeforeTerminating</code></p></td>
<td style="text-align: left;"><p>Optional: Specify whether the cluster autoscaler should cordon a node before removing that node by using one of the following values:</p>
<ul>
<li><p><code>Enabled</code>: The cluster autoscaler cordons the node before draining any pods and removing that node.</p></li>
<li><p><code>Disabled</code>: The cluster autoscaler does not cordon the node before draining any pods and removing that node. This is the default.</p></li>
</ul></td>
</tr>
<tr>
<td style="text-align: left;"><p><code>scaleDown.enabled</code></p></td>
<td style="text-align: left;"><p>Specify whether the cluster autoscaler can remove unnecessary nodes.</p></td>
</tr>
<tr>
<td style="text-align: left;"><p><code>scaleDown.delayAfterAdd</code></p></td>
<td style="text-align: left;"><p>Optional: Specify the period to wait before deleting a node after a node has recently been <em>added</em>. If you do not specify a value, the default value of <code>10m</code> is used.</p></td>
</tr>
<tr>
<td style="text-align: left;"><p><code>scaleDown.delayAfterDelete</code></p></td>
<td style="text-align: left;"><p>Optional: Specify the period to wait before deleting a node after a node has recently been <em>deleted</em>. If you do not specify a value, the default value of <code>0s</code> is used.</p></td>
</tr>
<tr>
<td style="text-align: left;"><p><code>scaleDown.delayAfterFailure</code></p></td>
<td style="text-align: left;"><p>Optional: Specify the period to wait before deleting a node after a scale down failure occurred. If you do not specify a value, the default value of <code>3m</code> is used.</p></td>
</tr>
<tr>
<td style="text-align: left;"><p><code>scaleDown.unneededTime</code></p></td>
<td style="text-align: left;"><p>Optional: Specify a period of time before an unnecessary node is eligible for deletion. If you do not specify a value, the default value of <code>10m</code> is used.</p></td>
</tr>
<tr>
<td style="text-align: left;"><p><code>scaleDown.utilizationThreshold</code></p></td>
<td style="text-align: left;"><p>Optional: Specify the <em>node utilization level</em>. Nodes below this utilization level are eligible for deletion.</p>
<p>The node utilization level is the sum of the requested resources divided by the allocated resources for the node, and must be a value greater than <code>"0"</code> but less than <code>"1"</code>. If you do not specify a value, the cluster autoscaler uses a default value of <code>"0.5"</code>, which corresponds to 50% utilization. You must express this value as a string.</p></td>
</tr>
<tr>
<td style="text-align: left;"><p><code>scaleUp</code></p></td>
<td style="text-align: left;"><p>In this section, you can specify the period to wait before recognizing newly pending pods by using any valid <a href="https://golang.org/pkg/time/#ParseDuration">ParseDuration</a> interval, including <code>ns</code>, <code>us</code>, <code>ms</code>, <code>s</code>, <code>m</code>, and <code>h</code>.</p></td>
</tr>
<tr>
<td style="text-align: left;"><p><code>scaleUp.newPodScaleUpDelay</code></p></td>
<td style="text-align: left;"><p>Optional: Specify the period to ignore a new unschedulable pod before adding a new node. If you do not specify a value, the default value of <code>0s</code> is used.</p></td>
</tr>
<tr>
<td style="text-align: left;"><p><code>expanders</code></p></td>
<td style="text-align: left;"><p>Optional: Specify any expanders that you want the cluster autoscaler to use. The following values are valid:</p>
<ul>
<li><p><code>LeastWaste</code>: Selects the machine set that minimizes the idle CPU after scaling. If multiple machine sets would yield the same amount of idle CPU, the selection minimizes unused memory.</p></li>
<li><p><code>Priority</code>: Selects the machine set with the highest user-assigned priority. To use this expander, you must create a config map that defines the priority of your machine sets. For more information, see "Configuring a priority expander for the cluster autoscaler."</p></li>
<li><p><code>Random</code>: (Default) Selects the machine set randomly.</p></li>
</ul>
<p>If you do not specify a value, the default value of <code>Random</code> is used.</p>
<p>You can specify multiple expanders by using the <code>[LeastWaste, Priority]</code> format. The cluster autoscaler applies each expander according to the specified order.</p>
<p>In the <code>[LeastWaste, Priority]</code> example, the cluster autoscaler first evaluates according to the <code>LeastWaste</code> criteria. If more than one machine set satisfies the <code>LeastWaste</code> criteria equally well, the cluster autoscaler then evaluates according to the <code>Priority</code> criteria. If more than one machine set satisfies all of the specified expanders equally well, the cluster autoscaler selects one to use at random.</p></td>
</tr>
</tbody>
</table>

> [!NOTE]
> When performing a scaling operation, the cluster autoscaler remains within the ranges set in the `ClusterAutoscaler` resource definition, such as the minimum and maximum number of cores to deploy or the amount of memory in the cluster. However, the cluster autoscaler does not correct the current values in your cluster to be within those ranges.
>
> The minimum and maximum CPUs, memory, and GPU values are determined by calculating those resources on all nodes in the cluster, even if the cluster autoscaler does not manage the nodes. For example, the control plane nodes are considered in the total memory in the cluster, even though the cluster autoscaler does not manage the control plane nodes.

## Configuring a priority expander for the cluster autoscaler

Configure a priority expander to control which machine set expands when the cluster autoscaler increases the size of the cluster. You can create a priority expander config map by listing priority values and regular expressions that define machine sets.

**Prerequisites**

- You have deployed an OpenShift Container Platform cluster that uses the Machine API.

- You have access to the cluster using an account with `cluster-admin` permissions.

- You have installed the OpenShift CLI (`oc`).

**Procedure**

1.  List the compute machine sets on your cluster by running the following command:

    ``` terminal
    $ oc get machinesets.machine.openshift.io
    ```

**Example output**

    ``` terminal
    NAME                                        DESIRED   CURRENT   READY   AVAILABLE   AGE
    archive-agl030519-vplxk-worker-us-east-1c   1         1         1       1           25m
    fast-01-agl030519-vplxk-worker-us-east-1a   1         1         1       1           55m
    fast-02-agl030519-vplxk-worker-us-east-1a   1         1         1       1           55m
    fast-03-agl030519-vplxk-worker-us-east-1b   1         1         1       1           55m
    fast-04-agl030519-vplxk-worker-us-east-1b   1         1         1       1           55m
    prod-01-agl030519-vplxk-worker-us-east-1a   1         1         1       1           33m
    prod-02-agl030519-vplxk-worker-us-east-1c   1         1         1       1           33m
    ```

2.  Using regular expressions, construct one or more patterns that match the name of any compute machine set that you want to set a priority level for.

    For example, use the regular expression pattern `*fast*` to match any compute machine set that includes the string `fast` in its name.

3.  Create a `cluster-autoscaler-priority-expander.yml` YAML file that defines a config map similar to the following:

**Example priority expander config map**

    ``` yaml
    apiVersion: v1
    kind: ConfigMap
    metadata:
      name: cluster-autoscaler-priority-expander
      namespace: openshift-machine-api
    data:
      priorities: |-
        10:
          - .*fast.*
          - .*archive.*
        40:
          - .*prod.*
    ```

    Define the priority of your machine sets. The `priorities` values must be positive integers. The cluster autoscaler uses higher-value priorities before lower-value priorities. For each priority level, specify the regular expressions that correspond to the machine sets you want to use.

4.  Create the config map by running the following command:

    ``` terminal
    $ oc create configmap cluster-autoscaler-priority-expander \
      --from-file=<location_of_config_map_file>/cluster-autoscaler-priority-expander.yml
    ```

**Verification**

- Review the config map by running the following command:

  ``` terminal
  $ oc get configmaps cluster-autoscaler-priority-expander -o yaml
  ```

**Next steps**

- To use the priority expander, ensure that the `ClusterAutoscaler` resource definition is configured to use the `expanders: ["Priority"]` parameter.

## Labeling GPU machine sets for the cluster autoscaler

Label your machine sets to indicate which machines the cluster autoscaler can use for GPU-enabled nodes. Applying the accelerator label helps ensure that the autoscaler deploys the correct resources for your GPU workloads.

**Prerequisites**

- Your cluster uses a cluster autoscaler.

**Procedure**

- On the machine set that you want to create machines for the cluster autoscaler to use to deploy GPU-enabled nodes, add a `cluster-api/accelerator` label:

  ``` yaml
  apiVersion: machine.openshift.io/v1beta1
  kind: MachineSet
  metadata:
    name: machine-set-name
  spec:
    template:
      spec:
        metadata:
          labels:
            cluster-api/accelerator: <accelerator_name>
  ```

  where:

  `<accelerator_name>`
  Specifies a label of your choice that consists of alphanumeric characters, `-`, `_`, or `.` and starts and ends with an alphanumeric character. For example, you might use `nvidia-t4` to represent Nvidia T4 GPUs, or `nvidia-a10g` for A10G GPUs.

  > [!NOTE]
  > You must specify the value of this label for the `spec.resourceLimits.gpus.type` parameter in your `ClusterAutoscaler` CR. For more information, see "Cluster autoscaler resource definition".

## Deploying a cluster autoscaler

To deploy a cluster autoscaler, you create an instance of the `ClusterAutoscaler` resource.

**Procedure**

1.  Create a YAML file for a `ClusterAutoscaler` resource that contains the custom resource definition.

2.  Create the custom resource in the cluster by running the following command:

    ``` terminal
    $ oc create -f <filename>.yaml
    ```

    where:

    \<filename\>
    Specifies the name of the YAML file you created.

# About the machine autoscaler

The machine autoscaler adjusts the number of Machines in the compute machine sets that you deploy in an OpenShift Container Platform cluster. You can scale both the default `worker` compute machine set and any other compute machine sets that you create. The machine autoscaler makes more Machines when the cluster runs out of resources to support more deployments. Any changes to the values in `MachineAutoscaler` resources, such as the minimum or maximum number of instances, are immediately applied to the compute machine set they target.

> [!IMPORTANT]
> You must deploy a machine autoscaler for the cluster autoscaler to scale your machines. The cluster autoscaler uses the annotations on compute machine sets that the machine autoscaler sets to determine the resources that it can scale. If you define a cluster autoscaler without also defining machine autoscalers, the cluster autoscaler will never scale your cluster.

## Configuring machine autoscalers

After you deploy the cluster autoscaler, deploy `MachineAutoscaler` resources that reference the compute machine sets that are used to scale the cluster.

> [!IMPORTANT]
> You must deploy at least one `MachineAutoscaler` resource after you deploy the `ClusterAutoscaler` resource.

> [!NOTE]
> You must configure separate resources for each compute machine set. Remember that compute machine sets are different in each region, so consider whether you want to enable machine scaling in multiple regions. The compute machine set that you scale must have at least one machine in it.

### Machine autoscaler resource definition

This `MachineAutoscaler` resource definition shows the parameters and sample values for the machine autoscaler.

``` yaml
apiVersion: "autoscaling.openshift.io/v1beta1"
kind: "MachineAutoscaler"
metadata:
  name: "worker-us-east-1a"
  namespace: "openshift-machine-api"
spec:
  minReplicas: 1
  maxReplicas: 12
  scaleTargetRef:
    apiVersion: machine.openshift.io/v1beta1
    kind: MachineSet
    name: worker-us-east-1a
```

where:

\<name\>
Specify the machine autoscaler name. To make it easier to identify which compute machine set this machine autoscaler scales, specify or include the name of the compute machine set to scale. The compute machine set name takes the following form: `<clusterid>-<machineset>-<region>`.

\<minReplicas\>
Specify the minimum number machines of the specified type that must remain in the specified zone after the cluster autoscaler initiates cluster scaling. If running in AWS, Google Cloud, Azure, RHOSP, or vSphere, this value can be set to `0`. For other providers, do not set this value to `0`.

You can save on costs by setting this value to `0` for use cases such as running expensive or limited-usage hardware that is used for specialized workloads, or by scaling a compute machine set with extra large machines. The cluster autoscaler scales the compute machine set down to zero if the machines are not in use.

> [!IMPORTANT]
> Do not set the `spec.minReplicas` value to `0` for the three compute machine sets that are created during the OpenShift Container Platform installation process for an installer provisioned infrastructure.

\<maxReplicas\>
Specify the maximum number machines of the specified type that the cluster autoscaler can deploy in the specified zone after it initiates cluster scaling. Ensure that the `maxNodesTotal` value in the `ClusterAutoscaler` resource definition is large enough to allow the machine autoscaler to deploy this number of machines.

\<scaleTargetRef\>
In this section, provide values that describe the existing compute machine set to scale.

\<kind\>
The `kind` parameter value is always `MachineSet`.

\<name\>
The `name` value must match the name of an existing compute machine set, as shown in the `metadata.name` parameter value.

## Deploying a machine autoscaler

To deploy a machine autoscaler, you create an instance of the `MachineAutoscaler` resource.

**Procedure**

1.  Create a YAML file for a `MachineAutoscaler` resource that contains the custom resource definition.

2.  Create the custom resource in the cluster by running the following command:

    ``` terminal
    $ oc create -f <filename>.yaml
    ```

    where:

    \<filename\>
    Specifies the name of the YAML file you created.

# Disabling a machine autoscaler

To disable a machine autoscaler, you delete the corresponding `MachineAutoscaler` custom resource (CR).

> [!NOTE]
> Disabling a machine autoscaler does not disable the cluster autoscaler. To disable the cluster autoscaler, follow the instructions in "Disabling the cluster autoscaler".

**Procedure**

1.  List the `MachineAutoscaler` CRs for the cluster by running the following command:

    ``` terminal
    $ oc get MachineAutoscaler -n openshift-machine-api
    ```

**Example output**

    ``` terminal
    NAME                 REF KIND     REF NAME             MIN   MAX   AGE
    compute-us-east-1a   MachineSet   compute-us-east-1a   1     12    39m
    compute-us-west-1a   MachineSet   compute-us-west-1a   2     4     37m
    ```

2.  Optional: Create a YAML file backup of the `MachineAutoscaler` CR by running the following command:

    ``` terminal
    $ oc get MachineAutoscaler/<machine_autoscaler_name> \
      -n openshift-machine-api \
      -o yaml> <machine_autoscaler_name_backup>.yaml
    ```

    where:

    \<machine_autoscaler_name_backup\>
    Specifies the file name in which to store the backup.

3.  Delete the `MachineAutoscaler` CR by running the following command:

    ``` terminal
    $ oc delete MachineAutoscaler/<machine_autoscaler_name> -n openshift-machine-api
    ```

**Example output**

    ``` terminal
    machineautoscaler.autoscaling.openshift.io "compute-us-east-1a" deleted
    ```

**Verification**

- To verify that the machine autoscaler is disabled, run the following command:

  ``` terminal
  $ oc get MachineAutoscaler -n openshift-machine-api
  ```

  The disabled machine autoscaler does not appear in the list of machine autoscalers.

**Next steps**

- If you need to re-enable the machine autoscaler, use the `<machine_autoscaler_name_backup>.yaml` backup file and follow the instructions in "Deploying a machine autoscaler".

# Disabling the cluster autoscaler

To disable the cluster autoscaler, you delete the corresponding `ClusterAutoscaler` resource.

> [!NOTE]
> Disabling the cluster autoscaler disables autoscaling on the cluster, even if the cluster has existing machine autoscalers.

**Procedure**

1.  List the `ClusterAutoscaler` resource for the cluster by running the following command:

    ``` terminal
    $ oc get ClusterAutoscaler
    ```

**Example output**

    ``` terminal
    NAME      AGE
    default   42m
    ```

2.  Optional: Create a YAML file backup of the `ClusterAutoscaler` CR by running the following command:

    ``` terminal
    $ oc get ClusterAutoscaler/default \
      -o yaml> <cluster_autoscaler_backup_name>.yaml
    ```

    where:

    \<cluster_autoscaler_backup_name\>
    Specifies the file name in which to store the backup.

3.  Delete the `ClusterAutoscaler` CR by running the following command:

    ``` terminal
    $ oc delete ClusterAutoscaler/default
    ```

**Example output**

    ``` terminal
    clusterautoscaler.autoscaling.openshift.io "default" deleted
    ```

**Verification**

- To verify that the cluster autoscaler is disabled, run the following command:

  ``` terminal
  $ oc get ClusterAutoscaler
  ```

**Expected output**

  ``` terminal
  No resources found
  ```

**Next steps**

- Disabling the cluster autoscaler by deleting the `ClusterAutoscaler` CR prevents the cluster from autoscaling but does not delete any existing machine autoscalers on the cluster. To clean up unneeded machine autoscalers, see "Disabling a machine autoscaler".

- If you need to re-enable the cluster autoscaler, use the `<cluster_autoscaler_name_backup>.yaml` backup file and follow the instructions in "Deploying a cluster autoscaler".

# Additional resources

- [Including pod priority in pod scheduling decisions in OpenShift Container Platform](../nodes/pods/nodes-pods-priority.xml#nodes-pods-priority)
