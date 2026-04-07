# Next Step Commands

## 1. Start API

```bash
cd /home/shulun/project/LightWorld/backend
./.venv/bin/mirofish-api
```

## 2. Create Simulation

```bash
cd /home/shulun/project/LightWorld/event_inputs/baike_wuda_event
curl -s http://127.0.0.1:5001/api/simulation/create \
  -H 'Content-Type: application/json' \
  -d @simulation_create.json
```

Copy the returned `simulation_id`.

## 3. Prepare Simulation

Edit `simulation_prepare.template.json`, replace `sim_xxx` with your real `simulation_id`, then run:

```bash
cd /home/shulun/project/LightWorld/event_inputs/baike_wuda_event
curl -s http://127.0.0.1:5001/api/simulation/prepare \
  -H 'Content-Type: application/json' \
  -d @simulation_prepare.template.json
```

## 4. Poll Prepare Status

```bash
curl -s http://127.0.0.1:5001/api/simulation/prepare/status \
  -H 'Content-Type: application/json' \
  -d '{"simulation_id":"sim_xxx"}'
```

Wait until `status` becomes `ready`.

## 5. Run Simulation

Edit `simulation_run.template.json`, replace `sim_xxx` with your real `simulation_id`, then run:

```bash
cd /home/shulun/project/LightWorld/event_inputs/baike_wuda_event
curl -s http://127.0.0.1:5001/api/simulation/run \
  -H 'Content-Type: application/json' \
  -d @simulation_run.template.json
```

## 6. Query Run Status

```bash
curl -s http://127.0.0.1:5001/api/simulation/sim_xxx/run-status/detail
```

## 7. CLI Run After Prepare

If `prepare` has already generated `simulation_config.json`, you can run directly:

```bash
cd /home/shulun/project/LightWorld/backend
./.venv/bin/mirofish-parallel-sim --config ./uploads/simulations/sim_xxx/simulation_config.json --no-wait
```
