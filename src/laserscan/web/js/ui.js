/* Small UI components shared by the app: dropdown / menu and a context menu. */
(function (root) {
  'use strict';

  const CHEVRON = '<svg class="dd-icon" viewBox="0 0 12 12"><path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  const open = new Set();

  function closeAll(except) { for (const d of open) if (d !== except) d.close(); }
  document.addEventListener('pointerdown', (e) => { for (const d of open) if (!d.el.contains(e.target)) d.close(); }, true);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeAll(); });

  /**
   * A dropdown (a select, or with `menu: true` a menu of actions).
   * options: [{label, value, kbd}]; onChange(value).
   */
  class Dropdown {
    constructor(el, { options = [], value = null, onChange = () => {}, menu = false, label = '' } = {}) {
      this.el = el;
      this.menu = menu;
      this.onChange = onChange;
      this.label = label;
      this.value = value;
      this.options = options;
      el.innerHTML = `<button class="dd-trigger" type="button"><span class="dd-label"></span>${CHEVRON}</button><div class="dd-content ${menu ? 'menu' : ''}" hidden></div>`;
      this.trigger = el.querySelector('.dd-trigger');
      this.content = el.querySelector('.dd-content');
      this.trigger.addEventListener('click', () => (this.content.hidden ? this.show() : this.close()));
      this.setOptions(options, value);
    }

    setOptions(options, value) {
      this.options = options;
      if (value !== undefined) this.value = value;
      this.content.innerHTML = '';
      for (const o of options) {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'dd-option' + (!this.menu && o.value === this.value ? ' sel' : '');
        b.innerHTML = `${o.label}${o.kbd ? `<span class="kbd">${o.kbd}</span>` : ''}`;
        b.addEventListener('click', () => { this.close(); if (!this.menu) this.setValue(o.value); this.onChange(o.value); });
        this.content.append(b);
      }
      this.renderLabel();
    }

    setValue(value) { this.value = value; this.setOptions(this.options); }

    renderLabel() {
      const found = this.options.find((o) => o.value === this.value);
      this.el.querySelector('.dd-label').textContent = this.menu ? this.label : (found ? found.label : (this.value ?? ''));
    }

    setDisabled(on) { this.trigger.disabled = on; if (on) this.close(); }

    show() { closeAll(this); this.content.hidden = false; this.el.classList.add('open'); open.add(this); }
    close() { this.content.hidden = true; this.el.classList.remove('open'); open.delete(this); }
  }

  /** Pop up a small menu at screen position (x, y); items: [{label, onClick}]. */
  function contextMenu(x, y, items) {
    const menu = document.createElement('div');
    menu.className = 'ctx';
    for (const it of items) {
      const b = document.createElement('button');
      b.className = 'dd-option';
      b.textContent = it.label;
      b.addEventListener('click', () => { remove(); it.onClick(); });
      menu.append(b);
    }
    document.body.append(menu);
    const r = menu.getBoundingClientRect();
    menu.style.left = Math.min(x, window.innerWidth - r.width - 8) + 'px';
    menu.style.top = Math.min(y, window.innerHeight - r.height - 8) + 'px';
    const remove = () => { menu.remove(); document.removeEventListener('pointerdown', away, true); };
    const away = (e) => { if (!menu.contains(e.target)) remove(); };
    setTimeout(() => document.addEventListener('pointerdown', away, true));
  }

  root.UI = { Dropdown, contextMenu };
})(window);
