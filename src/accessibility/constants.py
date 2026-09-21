ACTIONABLE_ROLES = {
    "button",
    "checkbox",
    "combobox",
    "link",
    "menuitem",
    "menuitemcheckbox",
    "menuitemradio",
    "option",
    "radio",
    "searchbox",
    "slider",
    "spinbutton",
    "switch",
    "tab",
    "textbox",
    "treeitem",
}
SKIPPED_ROLES = {"InlineTextBox", "LineBreak", "ListMarker", "none", "presentation"}
STATE_NAMES = {
    "checked",
    "disabled",
    "expanded",
    "focused",
    "hasPopup",
    "level",
    "pressed",
    "required",
    "selected",
    "url",
}
STRUCTURAL_ROLES = {
    "generic",
    "group",
    "paragraph",
    "list",
    "listitem",
    "separator",
    "presentation",
    "none",
}
PROTECTED_ROLES = {"alert", "dialog", "form", "heading", "main", "navigation"}
FOOTER_ESSENTIAL_ROLES = {"alert", "dialog", "form"}
# ponytail: 500 characters keeps page context bounded; raise this or summarize blocks
# by relevance when long-form page content needs more fidelity.
MAX_STATIC_TEXT_LENGTH = 500
