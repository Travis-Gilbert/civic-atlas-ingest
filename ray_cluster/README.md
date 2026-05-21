# Ray on RunPod Cluster Notes

`runpod.yaml` is the XRL-B-000 cluster-shape artifact. It records the node
roles, resource labels, environment variables, and startup commands expected by
the Civic Atlas ingest jobs after the Modal retirement.

RunPod does not provide a first-party Ray autoscaler provider in this repo.
Provision pods with the RunPod template/launcher, start the head node with the
commands in `head_start_ray_commands`, start workers with
`worker_start_ray_commands`, then submit jobs with `ray job submit` or deploy
Ray Serve with `serve run`.

Required runtime secrets stay outside git:

- `CIVIC_ATLAS_CORPUS_TOKEN`
- `CIVIC_ATLAS_TRAIN_TOKEN`
- `SCENE_FOUNDRY_TOKEN`
- S3 credentials for the `civic-atlas` bucket
- Optional W&B credentials for training reports
