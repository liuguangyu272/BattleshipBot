import argparse
import json
from pathlib import Path

from .core import save_json, verify_replay
from .arena import play, evaluate, benchmark
from .bots import Policy


def main():
    parser = argparse.ArgumentParser(description="Battleship / 海战棋实验室")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("demo", help="run one complete game and save replay")
    p.add_argument("--bot", default="champion")
    p.add_argument("--opponent", default="density")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--style", default="uniform")
    p.add_argument("--out", default="replays/demo.json")
    p = sub.add_parser("evaluate")
    p.add_argument("--bot", default="champion")
    p.add_argument("--opponents", nargs="+", default=["random", "hunt", "density"])
    p.add_argument("--pairs", type=int, default=100)
    p.add_argument("--seed-start", type=int, default=900000)
    p.add_argument("--styles", nargs="+", default=["uniform", "edge", "cluster"])
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--time-limit-ms", type=float, default=1000)
    p.add_argument("--out", default="results/evaluation")
    p = sub.add_parser("benchmark")
    p.add_argument("--bot", default="champion")
    p.add_argument("--boards", type=int, default=100)
    p.add_argument("--seed-start", type=int, default=1000)
    p.add_argument("--styles", nargs="+", default=["uniform"])
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--out", default="results/benchmark.json")
    p = sub.add_parser("train", help="reproducible policy parameter optimization")
    p.add_argument("--trials", type=int, default=12)
    p.add_argument("--boards", type=int, default=80)
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--out", default="policies/search")
    p = sub.add_parser("replay")
    p.add_argument("path")
    p = sub.add_parser("serve")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true")
    p = sub.add_parser("protocol")
    p.add_argument("--bot", default="champion")
    args = parser.parse_args()
    if args.command == "demo":
        result, replay = play((args.bot, args.opponent), args.seed, style=args.style)
        save_json(args.out, replay)
        result.pop("latency_ms")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print("Replay:", str(Path(args.out).resolve()))
    elif args.command == "evaluate":
        if args.pairs < 1 or args.workers < 1:
            parser.error("pairs and workers must be positive")
        evaluate(args.bot, args.opponents, args.pairs, args.seed_start, args.styles,
                 args.out, args.workers, args.time_limit_ms)
    elif args.command == "benchmark":
        result = benchmark(args.bot, range(args.seed_start, args.seed_start+args.boards), args.styles, workers=args.workers)
        save_json(args.out, result)
        print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))
    elif args.command == "train":
        from .optimize import optimize
        if args.boards < 1 or args.trials < 1 or args.workers < 1:
            parser.error("boards, trials, workers must be positive")
        optimize(args.out, args.trials, args.boards, args.workers)
    elif args.command == "replay":
        game = verify_replay(json.loads(Path(args.path).read_text(encoding="utf-8")))
        print(f"Replay verified: winner={game.winner}, plies={len(game.events)}")
    elif args.command == "serve":
        from .webui import serve
        serve(args.port, not args.no_browser)
    elif args.command == "protocol":
        from .protocol import run_protocol
        run_protocol(args.bot)


if __name__ == "__main__":
    main()
