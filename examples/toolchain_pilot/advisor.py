"""Optional experimental Julia score adapter. Advice never becomes CH evidence."""
import copy
import json
import math
import urllib.error
import urllib.parse
import urllib.request


def parse_reply(raw):
    try:
        body = json.loads(raw)
        score = body["answers"]["q1"]["noul"]
        if type(score) not in (float, int) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError("Score must be a finite number in [0,1]")
    except (ValueError, TypeError, KeyError) as exc:
        return {"status": "UNKNOWN", "reason": "Invalid/missing advisory score: " + str(exc)}
    return {"status": "OBSERVED", "label": "SUPPORTED" if score >= .5 else "NOT_SUPPORTED",
            "score": score, "authority": "advisory_only"}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.URLError("Advisory redirects are disabled")


def classify(state, endpoint=None, timeout=1.0, transport=None):
    if not endpoint:
        return {"status": "NOT_RUN", "reason": "No Julia endpoint configured"}
    url = urllib.parse.urlsplit(endpoint)
    if url.scheme != "http" or url.hostname not in ("localhost", "127.0.0.1", "::1") or url.username or url.password or url.fragment:
        raise ValueError("Use an explicit local HTTP Julia endpoint without credentials")
    if not 0 < timeout <= 5 or not math.isfinite(timeout):
        raise ValueError("Advisory timeout must be positive and at most five seconds")
    request = urllib.request.Request(endpoint, data=json.dumps({"state": state,
        "questions": {"q1": {"type": "noul", "instructions": "Does the stated test evidence support the claim?",
                               "options": {"true": "Supported", "false": "Not supported"}}}}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        if transport is None:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
                raw = response.read(16385)
        else:
            raw = transport(request, timeout)
        if len(raw) > 16384:
            return {"status": "UNKNOWN", "reason": "Advisory response exceeds 16 KiB"}
        return parse_reply(raw)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"status": "NOT_RUN", "reason": type(exc).__name__ + ": " + str(exc)}


def attach_advice(report, advice):
    # Keep the gate report byte-for-byte in meaning; no graph writes, SUPPORTS
    # relation, independent provenance root or automatic authorization.
    result = copy.deepcopy(report)
    result["julia_advisory"] = copy.deepcopy(advice)
    return result


def boundary_controls(failed_report):
    positive = parse_reply(b'{"answers":{"q1":{"noul":0.99}}}')
    negative = parse_reply(b'{"answers":{"q1":{"noul":0.01}}}')
    missing = parse_reply(b'{"answers":{"q1":{}}}')
    broken = parse_reply(b'not-json')
    def timeout(request, seconds):
        raise TimeoutError("controlled timeout; no network")
    timed = classify("synthetic fixture", "http://127.0.0.1:8011/v1/systemone", transport=timeout)
    attached = attach_advice(failed_report, positive)
    checks = {"valid_positive": positive.get("label") == "SUPPORTED",
              "valid_negative": negative.get("label") == "NOT_SUPPORTED",
              "missing_score_abstains": missing["status"] == "UNKNOWN" and "label" not in missing,
              "broken_json_abstains": broken["status"] == "UNKNOWN" and "label" not in broken,
              "timeout_abstains": timed["status"] == "NOT_RUN" and "label" not in timed,
              "no_endpoint_not_run": classify("synthetic fixture")["status"] == "NOT_RUN",
              "positive_advice_cannot_override_block": attached["gates"]["test"]["status"] == "block",
              "advice_preserves_gate_report": attached["gates"] == failed_report["gates"],
              "advice_preserves_no_adoption": attached["adoption_allowed"] is False and failed_report["adoption_allowed"] is False}
    return {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks,
            "model_call": False, "note": "Controlled parser/transport responses, not a live Julia result."}
