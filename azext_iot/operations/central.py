from knack.util import CLIError
from azext_iot.common._azure import get_event_hub_target_from_central_app_id
from azext_iot.operations.hub import iot_query

def iot_central_monitor_events(cmd, app_id, device_id=None, consumer_group='$Default', timeout=300, enqueued_time=None, 
                                repair=False, properties=None):
    import importlib
    from datetime import datetime
    from azext_iot.common.deps import ensure_uamqp
    from azext_iot.common.utility import validate_min_python_version

    validate_min_python_version(3, 5)

    if timeout < 0:
        raise CLIError('Monitoring timeout must be 0 (inf) or greater.')
    timeout = (timeout * 1000)

    config = cmd.cli_ctx.config
    output = cmd.cli_ctx.invocation.data.get("output", None)
    if not output:
        output = 'json'
    ensure_uamqp(config, repair)

    events3 = importlib.import_module('azext_iot.operations.events3._events')

    if not properties:
        properties = []

    def _calculate_millisec_since_unix_epoch_utc():
        now = datetime.utcnow()
        epoch = datetime.utcfromtimestamp(0)
        return int(1000 * (now - epoch).total_seconds())

    if not enqueued_time:
        enqueued_time = _calculate_millisec_since_unix_epoch_utc()

    target = {}
    target['central'] = get_event_hub_target_from_central_app_id(cmd, app_id)
    events3.executor(target,
                     consumer_group=consumer_group,
                     enqueued_time=enqueued_time,
                     properties=properties,
                     timeout=timeout,
                     device_id=device_id,
                     output=output,
                     device_ids=device_ids)
