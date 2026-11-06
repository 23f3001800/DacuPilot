import { marked } from "marked";
import DOMPurify from "dompurify";

DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node.tagName === "A") {
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noopener noreferrer");
  }
});

export function renderMarkdown(text) {
  return DOMPurify.sanitize(
    marked.parse(String(text || ""), { gfm: true, breaks: true, async: false }),
    {
      ALLOWED_TAGS: [
        "p",
        "br",
        "strong",
        "em",
        "del",
        "h1",
        "h2",
        "h3",
        "h4",
        "ul",
        "ol",
        "li",
        "blockquote",
        "pre",
        "code",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "a",
        "hr",
      ],
      ALLOWED_ATTR: ["href", "title", "target", "rel", "start"],
      ALLOW_DATA_ATTR: false,
    },
  );
}
