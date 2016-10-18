#!/usr/bin/env python

from __future__ import print_function

import argparse
import os
import sys
import chess
import chess.uci


def read_epd(fname):
    """Read epd file preserving empty lines so that in the output epd, the line
       number of the original position is preserved."""
    epd = []
    total = 0
    with open(fname, 'r') as f:
        for line in f:
            line = line.strip()
            epd.append(line)
            if line:
                total += 1
    return epd, total


def try_call(func, arglist):
    """Call func(arg) for each arg in arglist until no exception araises"""
    for arg in arglist:
        try:
            return func(arg)
        except:
            if arg == arglist[-1]:  # At the end
                return None


def parse_position(line):
    """Get fen and best move in san notation out of a line. It is quite robust
       to incomplete fen and especially to malformed best moves. We assume the
       checking for empty line is already done upstream."""

    # Now find the best move delimiter, it should be 'bm' but...
    sep = next((x for x in ['bm', 'am'] if x in line), None)
    if not sep:
        return None, None, "Invalid line {}\n\n".format(line)

    fen, san = line.split(sep)[:2]
    f = fen.split()
    arglist = [fen, ' '.join(f[:6]), ' '.join(f[:4]) + ' 0 1']
    board = try_call(chess.Board, arglist)
    if not board:
        return None, None, "Invalid fen {}\n\n".format(fen)

    san = san.replace(';', ' ').replace(',', ' ').replace('!', ' ').split()[0]
    san = san.replace('0-0-0', 'O-O-O').replace('0-0', 'O-O')
    arglist = [san, san + '+']
    move = try_call(board.parse_san, arglist)
    if not move:
        return None, None, "Invalid best move {}\n\n".format(san)

    return board, board.san(move), 'OK'


class EpdWriter(object):
    """Syntactic sugar class to append into the output epd file the successful
       positions that passed the test."""
    def __init__(self, result_epd):
        self.result_epd = result_epd
        open(result_epd, 'w').close()  # Clear output file

    def __call__(self, pos=''):
        with open(self.result_epd, 'a') as f:
            f.write(pos + '\n')


def prepare_engine(args):
    """Launch the engine and set hash size (in MB) and number of threads"""
    engine = chess.uci.popen_engine(args.engine)
    info_handler = chess.uci.InfoHandler()
    engine.info_handlers.append(info_handler)
    engine.uci()  # Send the mandatory uci command
    engine.setoption({"Hash": args.hash, "Threads": args.threads})
    if not engine.is_alive():
        engine.quit()
        return None
    return engine


def pretty(score):
    """Return a printable string out of a chess.uci.Score"""
    if score.mate:
        return str(score.mate) + '#'
    return str(score.cp)


def run_session(args, engine):
    """Main function that reads the epd testsuite and runs the engine on each
       position. Engine is first ran once, if best move is still not found then
       the provided best move is forced and the new position is researched:
       if the score of the second search is still lower than the first one (our
       baseline), then the position is very hard and test succeeded."""
    print_epd = EpdWriter(args.result_epd)
    epd, total = read_epd(args.testsuite)
    cnt = 0
    for pos in epd:
        if not pos:
            print_epd()  # Empty lines are preserved
            continue

        cnt += 1
        board, san, result = parse_position(pos)
        print("Position: {}/{}\nPos: {}".format(cnt, total, pos))
        if result != 'OK':
            print(result)
            print_epd(pos)  # Don't silently drop invalid positions
            continue

        engine.position(board)
        bestmove, _ = engine.go(movetime=args.movetime)
        score1 = engine.info_handlers[0].info["score"][1]
        bestmove = board.san(bestmove)
        print("Warm-up best move: {}, score: {}".format(bestmove, pretty(score1)))
        if bestmove == san:
            print("Best move already found!\n\n")
            print_epd()
            continue

        print("Forcing best move: {}".format(san))
        board.push_san(san)
        engine.position(board)
        bestmove, _ = engine.go(movetime=args.movetime)
        score2 = engine.info_handlers[0].info["score"][1]
        print("After forcing best move, score: {}\n\n".format(pretty(score2)))

        # If score after searching known best move is not higher than baseline
        # then test is passed. Note that sign is inverted for score2.
        is_hard = not score1.mate and not score2.mate and score1.cp >= -score2.cp
        print_epd(pos if is_hard else '')


if __name__ == "__main__":
    p = argparse.ArgumentParser(description='Run DBT test on a epd testsuite')
    p.add_argument("engine", help="Path to the chess engine")
    p.add_argument("testsuite", help="Path to the epd input file")
    p.add_argument("--movetime", help="Time for position in milliseconds", type=int, default=10000)
    p.add_argument("--threads", help="Number of threads", type=int, default=3)
    p.add_argument("--hash", help="Hash table size in MB", type=int, default=1024)
    args = p.parse_args()

    if not os.path.isfile(args.testsuite):
        print("Testsuite {} not found.".format(args.testsuite))
        sys.exit(0)

    if not os.path.isfile(args.engine):
        print("Engine {} not found.".format(args.engine))
        sys.exit(0)

    engine = prepare_engine(args)
    if not engine:
        print("Unable to launch {}.".format(args.engine))
        sys.exit(0)

    name = args.testsuite.split('.epd')[0]
    args.result_epd = name + '_' + str(args.movetime / 1000) + 'sec.epd'

    print("Running DBT on: {}\nTime per position: {} millisec\nOutput: {}\n\n"
          .format(args.testsuite, args.movetime, args.result_epd))

    run_session(args, engine)
    engine.quit()
