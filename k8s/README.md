# kubernetes-related bits

## hack/build

In the [build](./build) directory you'll find scripts to build a base `python3` image, along with the `portal-to-jira-sync` image on top. 

You can also run a local instance of the container by creating `cfg/t5g.cfg` and running `run.sh`.

## deployment

The container is currently run as a cronjob every 30 minutes under the `portal-to-jira-sync` project in the lab's OpenShift cluster. To deploy, make a copy of [yaml/sample-config-map.yml](sample-config-map.yml) to suite your environment, then:

```
oc apply -f config-map.yml
oc apply -f cronjob.yml
```
