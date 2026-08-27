/* Tarjeta de métricas por recruiter — COMPARTIDA entre docs/cv-review.html y
   docs/recruiter-power.html (pestaña "CV quality").
   Estilos en assets/css/cv-review-cards.css.

   Por qué un módulo y no una copia en cada página: las dos pintan la MISMA tarjeta con la
   MISMA respuesta de GET /cv_reviews/metrics. Dos copias del cálculo de porcentajes y de
   la barra partida se desincronizan, y el resultado es que dos pantallas dicen cosas
   distintas del mismo recruiter — que es exactamente lo que estas métricas no pueden
   permitirse, porque se usan para evaluar gente.

   Se expone en `window.CvReviewCards`. Sin módulos ES a propósito: docs/ carga todo con
   <script> planos y ninguna otra página de este repo usa import/export. */
(function () {
  'use strict';

  const esc = (s) => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');

  // Semáforo del anillo. Los cortes son los mismos que usa la cola de CV Review.
  const qCls = (s) => (s === null || s === undefined) ? 'cvr-q-none'
    : s >= 75 ? 'cvr-q-good' : s >= 50 ? 'cvr-q-mid' : 'cvr-q-low';

  // Con n chico el porcentaje engaña: 1 de 20 es 5 por ciento, y "5%" solo parece una
  // tendencia. Siempre se muestra el conteo al lado.
  function fmtRate(count, total, pct) {
    if (!total) return '—';
    const p = (pct === null || pct === undefined) ? Math.round(1000 * count / total) / 10 : pct;
    return `${count}/${total} · ${p}%`;
  }

  // pathLength="100" deja poner el dasharray directo en porcentaje, sin calcular la
  // circunferencia.
  function ringHtml(score, modCls) {
    const pct = Math.max(0, Math.min(100, Number(score) || 0));
    return `<span class="cvr-cov ${modCls || ''}">
        <svg class="cvr-ring ${qCls(score)}" viewBox="0 0 36 36" aria-hidden="true">
          <circle class="cvr-ring-t" cx="18" cy="18" r="16" pathLength="100"></circle>
          <circle class="cvr-ring-p" cx="18" cy="18" r="16" pathLength="100"
                  stroke-dasharray="${pct} 100"></circle>
        </svg>
        <span class="cvr-cov-n">${score}</span>
      </span>`;
  }

  /* Una tarjeta. `r` es una fila de GET /cv_reviews/metrics (o el objeto `totals`). */
  function card(r, isTotal) {
    const q = r.quality_avg;
    const hasQ = q !== null && q !== undefined;

    // Aprobado y rechazado en primera son las dos mitades de lo MISMO (lo que ya
    // decidiste), así que van en una sola barra partida en vez de dos porcentajes
    // sueltos que el ojo tiene que sumar.
    const dec = r.profiles_decided || 0;
    const ap = r.approved_first_try_pct;
    const rj = r.rejected_first_try_pct;
    // Tres tramos, no dos: "devuelto para corregir" no es ni aprobado ni rechazado, y
    // sumarlo a cualquiera de los dos miente en la dirección que más importa — el
    // rechazo es sobre el candidato, la corrección es sobre el documento.
    // El tramo va siempre (0 % es ancho 0) pero la leyenda sólo si hubo alguno: una
    // línea que dice "0% needs changes" en cada tarjeta es ruido.
    const ch = r.changes_first_try_pct || 0;
    const split = dec
      ? `<div class="cvr-split" role="img"
              aria-label="${ap} per cent approved on the first try, ${ch} per cent sent back for changes, ${rj} per cent rejected">
           <i class="cvr-split-a" style="width:${ap}%"></i>
           <i class="cvr-split-c" style="width:${ch}%"></i>
           <i class="cvr-split-r" style="width:${rj}%"></i>
         </div>
         <div class="cvr-split-legend">
           <span class="cvr-lg-a"><b>${ap}%</b> approved 1st try</span>
           ${ch ? `<span class="cvr-lg-c"><b>${ch}%</b> needs changes</span>` : ''}
           <span class="cvr-lg-r"><b>${rj}%</b> rejected</span>
         </div>
         <p class="cvr-split-base">over ${dec} decided profile${dec === 1 ? '' : 's'}</p>`
      : `<p class="cvr-split-base cvr-split-base--empty">Nothing decided yet in this period.</p>`;

    const reasons = (r.reasons || []).map(x =>
      `<li><span>${esc(x.reason_label)}</span>
           <b>${fmtRate(x.profiles, r.profiles_decided, x.pct)}</b></li>`).join('');

    // Las salvedades eran cuatro renglones de gris repetidos en cada tarjeta. Van como
    // chips con el porqué en el tooltip: se ven de un vistazo y se leen si te importan.
    const chip = (n, label, why) => n
      ? `<span class="cvr-mchip" title="${esc(why)}"><b>${n}</b> ${esc(label)}</span>` : '';
    const chips = [
      chip(r.profiles_pending, 'pending',
           'Still waiting on your decision. The rates only count profiles you already decided.'),
      chip(r.stale_version_profiles, 'old rubric',
           'Scored under the old rubric, which measured the writing instead of JD coverage. Excluded from the coverage average.'),
      chip(r.unscored_profiles, 'unscored',
           'No AI score: the vacancy had no job description, or the scoring failed.'),
    ].filter(Boolean).join('');

    return `
      <article class="cvr-mcard ${isTotal ? 'cvr-mcard--total' : ''}">
        <div class="cvr-mcard-head">
          <h3>${esc(isTotal ? 'All recruiters' : (r.recruiter_label || r.recruiter_email))}</h3>
          <span class="cvr-mcard-sent"><b>${r.profiles_sent}</b> sent</span>
        </div>

        <div class="cvr-mcard-hero">
          ${hasQ ? ringHtml(q, 'cvr-cov--lg') : '<span class="cvr-cov--lg cvr-cov-empty">—</span>'}
          <div class="cvr-hero-txt">
            <div class="cvr-hero-l">JD coverage</div>
            <div class="cvr-hero-s">${hasQ
              ? `average of ${r.quality_n} first-round CV${r.quality_n === 1 ? '' : 's'}`
              : 'no scored CVs in this period'}</div>
          </div>
        </div>

        <div class="cvr-mcard-split">${split}</div>

        ${reasons ? `<p class="cvr-reasons-cap">Why they were rejected</p>
                     <ul class="cvr-reasons-list">${reasons}</ul>` : ''}
        ${chips ? `<div class="cvr-mchips">${chips}</div>` : ''}
      </article>`;
  }

  /* `by_reason` viene por (recruiter, razón); el total hay que sumarlo. `labels` es el
     mapa code -> etiqueta que cada página ya cargó de GET /cv_review_reasons. */
  function aggregateReasons(byReason, decided, labels) {
    const acc = {};
    (byReason || []).forEach(r => { acc[r.reason_code] = (acc[r.reason_code] || 0) + r.profiles; });
    return Object.entries(acc)
      .sort((a, b) => b[1] - a[1])
      .map(([code, profiles]) => ({
        reason_code: code,
        reason_label: (labels || {})[code] || code,
        profiles,
        pct: decided ? Math.round(1000 * profiles / decided) / 10 : null,
      }));
  }

  /* La fila "All recruiters": los totales que ya calculó el backend + las razones sumadas. */
  function totalsRow(data, labels) {
    const totals = data.totals || {};
    return {
      ...totals,
      recruiter_label: 'All recruiters',
      reasons: aggregateReasons(data.by_reason, totals.profiles_decided, labels),
    };
  }

  window.CvReviewCards = { card, ringHtml, qCls, fmtRate, aggregateReasons, totalsRow };
})();
