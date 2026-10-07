const MESSAGE_SELECTOR = '[data-message-author-role="user"], [data-message-author-role="assistant"]';
const EXCLUDED = 'button, svg, script, style, [hidden], [aria-hidden="true"], [data-token-hud-root], [data-testid="copy-turn-action-button"], [data-testid="thought-summary"], [data-testid="webpage-citation-pill"]';
const BLOCKS = new Set(['P', 'DIV', 'PRE', 'LI', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'TR', 'BLOCKQUOTE']);

function visible(element) {
  if (element.closest('[hidden], [aria-hidden="true"]')) return false;
  const view = element.ownerDocument.defaultView;
  for (let ancestor = element; ancestor; ancestor = ancestor.parentElement) {
    const style = view.getComputedStyle(ancestor);
    if (style.display === 'none' || style.visibility === 'hidden' || style.visibility === 'collapse') return false;
  }
  return element.getClientRects().length > 0 || view.getComputedStyle(element).display === 'contents';
}

function readText(node) {
  if (node.nodeType === 3) return node.nodeValue;
  if (node.nodeType !== 1 || node.matches(EXCLUDED) || !visible(node)) return '';
  if (node.tagName === 'BR') return '\n';
  // Code-block controls can include a language label outside the button.
  if (node.tagName === 'DIV' && node.querySelector('button') && !node.querySelector('pre') &&
      node.parentElement?.querySelector('pre')) return '';
  const text = [...node.childNodes].map(readText).join('');
  return BLOCKS.has(node.tagName) ? `${text}\n` : text;
}

export function collectMessages(document) {
  return [...document.querySelectorAll(MESSAGE_SELECTOR)]
    .filter(element => !element.parentElement?.closest(MESSAGE_SELECTOR) && visible(element))
    .map(element => {
      const role = element.getAttribute('data-message-author-role');
      const explicit = element.querySelector('[data-message-content]');
      let contents;
      if (explicit) contents = [explicit];
      else if (role === 'user') contents = [element.querySelector('.whitespace-pre-wrap') ?? element];
      else {
        contents = [...element.querySelectorAll('.markdown')]
          .filter(content => !content.parentElement?.closest('.markdown'));
        // Text-only message roots are safe; arbitrary assistant UI is not.
        if (!contents.length && element.children.length === 0) contents = [element];
      }
      if (!contents.length) return null;
      return { element, role, text: contents.map(readText).join('\n').trim() };
    }).filter(Boolean);
}
