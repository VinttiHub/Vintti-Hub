/* =========================================================
   STICKY SHELL — footer de la tabla
   Complemento de assets/css/sticky-shell.css.

   DataTables renderiza el info + la paginación DENTRO del contenedor que
   scrollea. El `dom:` de cada tabla los agrupa en un <div class="dt-sticky-footer">
   ('lrt<"dt-sticky-footer"ip>' en crm.js, main.js y candidate.js).

   Intentamos primero fijarlo con position:sticky, pero cada página tiene su
   propio contenedor de scroll —y candidates tiene dos anidados—, así que el
   sticky se anclaba al elemento equivocado y quedaban filas por encima y por
   debajo del footer.

   Solución determinista: mover el footer FUERA del contenedor que scrollea, y
   dejarlo como hermano justo debajo. Al no estar dentro del área scrolleable,
   no se puede ir con el scroll. Sin sticky, sin z-index, sin fondos que tapar.

   No hace falta tocar el JS de cada página: este script detecta el footer solo
   (incluso cuando DataTables se destruye y se reinicializa, como hace el CRM).
   ========================================================= */
(function () {
  'use strict';

  function isScroller(el) {
    const oy = getComputedStyle(el).overflowY;
    return oy === 'auto' || oy === 'scroll';
  }

  /** Sube hasta el contenedor scrolleable más cercano y deja el footer debajo. */
  function relocate(footer) {
    let el = footer.parentElement;
    while (el && el !== document.body) {
      if (isScroller(el)) {
        const parent = el.parentElement;
        if (!parent) return;
        // TODO EL CSS de DataTables cuelga de `.dataTables_wrapper ...`
        // (floats del info/paginación, estilo de los botones). Al sacar el
        // footer del wrapper deja de aplicarle nada y queda como texto pelado,
        // así que le ponemos la clase al propio footer para que siga heredando.
        footer.classList.add('dataTables_wrapper');
        parent.insertBefore(footer, el.nextSibling);
        // El CRM destruye y recrea su DataTable en cada carga. Como el footer
        // ya no está dentro del wrapper, destroy() no se lo lleva y quedaría
        // huérfano: sin esto se irían acumulando footers en cada refresh.
        parent.querySelectorAll(':scope > .dt-sticky-footer').forEach(function (other) {
          if (other !== footer) other.remove();
        });
        return;
      }
      el = el.parentElement;
    }
    // Sin contenedor scrolleable (p. ej. en mobile, donde scrollea la página
    // entera): se queda donde está, que es el comportamiento de siempre.
  }

  function scan() {
    document.querySelectorAll('.dt-sticky-footer').forEach(function (footer) {
      if (footer.dataset.footerMounted === '1') return;
      // Marcar ANTES de mover: mover dispara el observer de nuevo.
      footer.dataset.footerMounted = '1';
      relocate(footer);
    });
  }

  /* ---------- Modo compacto ----------
     Un botón en el header esconde el banner de mood y los filtros, y achica el
     header, para que la tabla gane alto. La preferencia se guarda y se comparte
     entre opportunities, crm y candidates: quien lo compacta en una lo quiere
     compactado en las tres. */
  const COMPACT_KEY = 'vintti_tables_compact';

  function applyCompact(on) {
    document.body.classList.toggle('is-compact', on);
    try { localStorage.setItem(COMPACT_KEY, on ? '1' : '0'); } catch (e) {}
    const btn = document.querySelector('.compact-toggle');
    if (!btn) return;
    // Texto explícito, no sólo un chevron: el botón tiene que decir qué hace.
    const label = on ? 'Show filters' : 'Hide filters';
    const labelEl = btn.querySelector('.compact-toggle-label');
    if (labelEl) labelEl.textContent = label;
    btn.setAttribute('aria-expanded', String(!on));
    btn.title = on
      ? 'Show the filters again'
      : 'Hide the filters to make the table taller';
    btn.setAttribute('aria-label', btn.title);
  }

  function mountCompactToggle() {
    const header = document.querySelector('.main-content > .page-header');
    if (!header || header.querySelector('.compact-toggle')) return;

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'compact-toggle';
    const icon = document.createElement('span');
    icon.className = 'compact-toggle-icon';
    icon.setAttribute('aria-hidden', 'true');
    icon.textContent = '⌃';
    const label = document.createElement('span');
    label.className = 'compact-toggle-label';
    btn.appendChild(icon);
    btn.appendChild(label);
    btn.addEventListener('click', function () {
      applyCompact(!document.body.classList.contains('is-compact'));
    });
    (header.querySelector('.page-actions') || header).appendChild(btn);

    // Por defecto arranca COMPACTADO: la tabla es lo que la gente viene a ver,
    // y los filtros quedan a un click. Sólo se respeta otra cosa si el usuario
    // ya eligió explícitamente.
    let saved = null;
    try { saved = localStorage.getItem(COMPACT_KEY); } catch (e) {}
    applyCompact(saved === null ? true : saved === '1');
  }

  function start() {
    mountCompactToggle();
    scan();
    // DataTables crea el footer después de que carguen los datos, y el CRM
    // destruye y recrea la tabla en cada refresh.
    new MutationObserver(scan).observe(document.body, {
      childList: true,
      subtree: true
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
