"""Facade tying the storage engine to the SkeinQL parser/executor."""
from .query.executor import execute
from .query.parser import parse


def run(graph, text: str, explain: bool = False):
    stmt = parse(text)
    return execute(graph, stmt, explain=explain)
