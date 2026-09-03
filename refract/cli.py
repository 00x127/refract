from __future__ import annotations

import argparse
import sys

import httpx

from . import __version__, client, crawl, graphql, render
from .active import Active
from .confirm import Confirm
from .engine import Engine
from .triage import analyse


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="refract",
        description="recover an API's request schema from its own validation errors.",
    )
    src = p.add_argument_group("target")
    src.add_argument("-r", "--request", metavar="FILE", help="raw HTTP request file (Burp style)")
    src.add_argument("-u", "--url", help="target URL")
    src.add_argument("-X", "--method", default="POST", help="HTTP method for -u (default POST)")
    src.add_argument("-H", "--header", action="append", default=[], help="header, repeatable")
    src.add_argument("-d", "--data", help="request body for -u")
    src.add_argument("--cookie", help="cookie header value, e.g. 'session=abc'")
    src.add_argument("--bearer", help="bearer token (sets Authorization header)")
    src.add_argument("--http", action="store_true", help="use http:// when reading a raw request")
    src.add_argument("--mode", choices=["auto", "json", "form", "query", "graphql"],
                     default="auto", help="request encoding (default auto-detect)")

    net = p.add_argument_group("network")
    net.add_argument("--proxy", help="upstream proxy, e.g. http://127.0.0.1:8080")
    net.add_argument("-k", "--insecure", action="store_true", help="skip TLS verification")
    net.add_argument("--rounds", type=int, default=24, help="max probe rounds (default 24)")
    net.add_argument("--delay", type=float, default=0.0, help="seconds to wait between requests")
    net.add_argument("--inject", action="store_true",
                     help="active pass: test injection and mass-assignment on recovered fields")
    net.add_argument("--confirm", action="store_true",
                     help="prove mass-assignment: set a field, then read the object back to see if it stuck")
    net.add_argument("--read", metavar="URL",
                     help="read-back endpoint for --confirm (GET); auto-detected if omitted")
    net.add_argument("--crawl", action="store_true",
                     help="spider the target (-u is the base), find endpoints and probe each")
    net.add_argument("--max-endpoints", type=int, default=40,
                     help="max endpoints to probe in crawl mode (default 40)")

    out = p.add_argument_group("output")
    out.add_argument("--json", action="store_true", help="emit JSON")
    out.add_argument("--proto", action="store_true", help="emit a .proto sketch")
    out.add_argument("--poc", action="store_true", help="print a curl PoC per lead")
    out.add_argument("--no-color", action="store_true", help="disable colour")
    out.add_argument("-v", "--verbose", action="store_true", help="log each round")
    out.add_argument("-o", "--output", help="write result to a file")

    p.add_argument("--version", action="version", version=f"refract {__version__}")
    return p


def load_request(args) -> client.Request:
    if args.request:
        req = client.from_raw(args.request, scheme="http" if args.http else "https")
    elif args.url:
        req = client.from_args(args.url, args.method, args.header, args.data)
    else:
        raise SystemExit("error: provide -r <file> or -u <url>")
    if args.cookie:
        req.headers["Cookie"] = args.cookie
    if args.bearer:
        req.headers["Authorization"] = f"Bearer {args.bearer}"
    return req


def pick_mode(args, req: client.Request) -> str:
    if args.mode != "auto":
        return args.mode
    if graphql.looks_like_graphql(req):
        return "graphql"
    ctype = next((v for k, v in req.headers.items() if k.lower() == "content-type"), "").lower()
    if "x-www-form-urlencoded" in ctype:
        return "form"
    if req.method.upper() == "GET" and not req.body.strip():
        return "query"
    return "json"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    req = load_request(args)
    mode = pick_mode(args, req)
    colour = sys.stdout.isatty() and not args.no_color

    net = client.Client(proxy=args.proxy, insecure=args.insecure, delay=args.delay)
    try:
        if args.crawl:
            base = args.url or args.request
            endpoints, findings = crawl.spider(net, base, dict(req.headers),
                                               max_endpoints=args.max_endpoints, verbose=args.verbose)
            text = render.crawl_report(base, endpoints, findings, colour)
            return _emit(text, args.output)

        if mode == "graphql":
            gql = graphql.recover(net, req)
            text = render.graphql_json(gql) if args.json else render.graphql_report(gql, colour)
            return _emit(text, args.output)

        signals = None
        confirmations = None
        read_endpoint = None
        result = Engine(net, req, max_rounds=args.rounds, verbose=args.verbose, encoding=mode).run()
        leads = analyse(result.schema.root)
        if args.inject:
            signals, _ = Active(net, req, result.schema, encoding=mode).run(leads)
        if args.confirm:
            confirmations, read_endpoint = Confirm(net, req, result.schema,
                                                   encoding=mode, read_url=args.read).run(leads)
    except httpx.RequestError as exc:
        print(f"error: request failed ({exc.__class__.__name__}): {exc}", file=sys.stderr)
        return 2
    finally:
        net.close()

    if args.json:
        text = render.as_json(result, leads, signals, confirmations)
    elif args.proto:
        text = render.as_proto(result)
    else:
        text = _report(req, result, leads, signals, confirmations, read_endpoint, args.poc, colour)

    return _emit(text, args.output)


def _emit(text: str, output: str | None) -> int:
    if output:
        with open(output, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
        print(f"written to {output}")
    else:
        print(text)
    return 0


def _report(req, result, leads, signals, confirmations, read_endpoint, show_poc: bool, colour: bool) -> str:
    import json as _json

    blocks = [render.tree(result, colour), "", render.leads_block(leads, colour)]
    leaks = render.leaks_block(result, colour)
    if leaks:
        blocks += ["", leaks]
    if signals is not None:
        blocks += ["", render.signals_block(signals, colour)]
    if confirmations is not None:
        blocks += ["", render.confirmations_block(confirmations, read_endpoint, colour)]
    blocks += ["", render._paint("valid request", "bold", colour),
               _json.dumps(render.skeleton(result), indent=2)]
    if show_poc:
        poc = render.poc_block(req, result, leads, colour)
        if poc:
            blocks += ["", poc]
    return "\n".join(blocks)


if __name__ == "__main__":
    raise SystemExit(main())
