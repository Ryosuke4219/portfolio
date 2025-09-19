import threading, time
from typing import Optional
from .provider_spi import ProviderSPI, ProviderRequest, ProviderResponse
from .metrics import log_event

def run_with_shadow(primary: ProviderSPI, shadow: Optional[ProviderSPI], req: ProviderRequest, metrics_path: str = "artifacts/runs-metrics.jsonl") -> ProviderResponse:
    shadow_rec = {}
    if shadow:
        def _shadow():
            ts0 = time.time()
            try:
                r = shadow.invoke(req)
                shadow_rec.update({
                    "ok": True,
                    "latency_ms": r.latency_ms,
                    "text_len": len(r.text),
                    "provider": shadow.name(),
                })
            except Exception as e:
                shadow_rec.update({"ok": False, "error": type(e).__name__, "provider": shadow.name()})
            finally:
                shadow_rec["duration_ms"] = int((time.time()-ts0)*1000)
        th = threading.Thread(target=_shadow, daemon=True)
        th.start()
    # primary (blocking)
    primary_res = primary.invoke(req)

    if shadow:
        th.join(timeout=10)
        log_event("shadow_diff", metrics_path,
                  primary_provider=primary.name(),
                  shadow_provider=shadow.name(),
                  primary_latency_ms=primary_res.latency_ms,
                  shadow_ok=shadow_rec.get("ok"),
                  shadow_latency_ms=shadow_rec.get("latency_ms"),
                  shadow_error=shadow_rec.get("error"))
    return primary_res
