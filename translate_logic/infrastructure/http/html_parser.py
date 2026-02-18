from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Callable


@dataclass(slots=True)
class HtmlNode:
    tag: str
    attrs: dict[str, str]
    parent: "HtmlNode | None"
    children: list["HtmlNode"]
    segments: list["HtmlSegment"]

    def classes(self) -> set[str]:
        class_attr = self.attrs.get("class", "")
        return {part for part in class_attr.split() if part}

    def text_content(self) -> str:
        parts: list[str] = []
        for segment in self.segments:
            if isinstance(segment, str):
                parts.append(segment)
            else:
                parts.append(segment.text_content())
        return "".join(parts)


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = HtmlNode("document", {}, None, [], [])
        self._stack: list[HtmlNode] = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key: value for key, value in attrs if key and value is not None}
        node = HtmlNode(tag, attrs_dict, self._stack[-1], [], [])
        self._stack[-1].children.append(node)
        self._stack[-1].segments.append(node)
        self._stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        if len(self._stack) > 1:
            self._stack.pop()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key: value for key, value in attrs if key and value is not None}
        node = HtmlNode(tag, attrs_dict, self._stack[-1], [], [])
        self._stack[-1].children.append(node)
        self._stack[-1].segments.append(node)

    def handle_data(self, data: str) -> None:
        if data:
            self._stack[-1].segments.append(data)


def parse_html(text: str) -> HtmlNode:
    builder = _TreeBuilder()
    builder.feed(text)
    return builder.root


def find_all(root: HtmlNode, predicate: Callable[[HtmlNode], bool]) -> list[HtmlNode]:
    matches: list[HtmlNode] = []
    stack: list[HtmlNode] = [root]
    while stack:
        node = stack.pop()
        if predicate(node):
            matches.append(node)
        stack.extend(reversed(node.children))
    return matches


def find_first(
    root: HtmlNode, predicate: Callable[[HtmlNode], bool]
) -> HtmlNode | None:
    stack: list[HtmlNode] = [root]
    while stack:
        node = stack.pop()
        if predicate(node):
            return node
        stack.extend(reversed(node.children))
    return None


def has_ancestor_with_class(node: HtmlNode, class_name: str) -> bool:
    current = node.parent
    while current is not None:
        if class_name in current.classes():
            return True
        current = current.parent
    return False


HtmlSegment = str | HtmlNode
