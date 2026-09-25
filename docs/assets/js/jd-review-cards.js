/* Tarjeta de métricas por recruiter del JD Review — COMPARTIDA entre docs/jd-review.html y
   docs/recruiter-power.html (pestaña "JD quality"). Misma idea que cv-review-cards.js: las
   dos pantallas pintan la MISMA tarjeta con la MISMA respuesta de GET /jd_reviews/metrics,
   así no pueden decir cosas distintas del mismo recruiter.

   Depende de window.CvReviewCards (anillo y formato de tasas): cargar cv-review-cards.js antes.
   Se expone en `window.JdReviewCards`. */
(function () {
  'use strict';

  const C = window.CvReviewCards;
  const esc = (s) => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');

  /* Una tarjeta. `r` es una fila de GET /jd_reviews/metrics (o el objeto `totals`). */
  function card(r, isTotal) {
    const q = r.quality_avg;
    const hasQ = q !== null && q !== undefined;
    const dec = r.jds_decided || 0;
    const ap = r.approved_first_try_pct || 0;
    const ch = r.changes_first_try_pct || 0;
    const split = dec
      ? `<div class="cvr-split" role="img" aria-label="${ap} per cent approved on the first try, ${ch} per cent sent back">
           <i class="cvr-split-a" style="width:${ap}%"></i>
           <i class="cvr-split-c" style="width:${ch}%"></i>
         </div>
         <div class="cvr-split-legend">
           <span class="cvr-lg-a"><b>${ap}%</b> approved 1st try</span>
           <span class="cvr-lg-c"><b>${ch}%</b> needs changes</span>
         </div>
         <p class="cvr-split-base">over ${dec} decided JD${dec === 1 ? '' : 's'}</p>`
      : '<p class="cvr-split-base cvr-split-base--empty">Nothing decided yet in this period.</p>';

    const rate = (n, d, pct) => C.fmtRate(n, d, pct);
    const stats = [
      r.missing_avg !== null && r.missing_avg !== undefined
        ? `<li><span>Points from the calls missing, avg</span><b>${r.missing_avg}</b></li>` : '',
      r.quality_n ? `<li><span>States something differently</span><b>${rate(r.with_contradictions, r.quality_n, r.with_contradictions_pct)}</b></li>` : '',
      r.quality_n ? `<li><span>Adds requirements nobody asked for</span><b>${rate(r.with_invented, r.quality_n, r.with_invented_pct)}</b></li>` : '',
    ].join('');
    const checklist = (r.checklist || []).map(x =>
      `<li><span>${esc(x.item_label)}</span><b>${rate(x.jds, r.jds_checklisted, x.pct)}</b></li>`).join('');

    const chip = (n, label, why) => n
      ? `<span class="cvr-mchip" title="${esc(why)}"><b>${n}</b> ${esc(label)}</span>` : '';
    const chips = [
      chip(r.jds_pending, 'pending', 'Still waiting on a decision. The rates only count decided JDs.'),
      chip(r.no_transcripts, 'no recordings', 'The opportunity had no usable Grain recording, so the JD could not be scored.'),
      chip(r.stale_version_jds, 'old rubric', 'Scored with an older version of the analysis. Excluded from the average.'),
    ].filter(Boolean).join('');

    return `
      <article class="cvr-mcard ${isTotal ? 'cvr-mcard--total' : ''}">
        <div class="cvr-mcard-head">
          <h3>${esc(isTotal ? 'All recruiters' : (r.recruiter_label || r.recruiter_email))}</h3>
          <span class="cvr-mcard-sent"><b>${r.jds_sent}</b> sent</span>
        </div>
        <div class="cvr-mcard-hero">
          ${hasQ ? C.ringHtml(q, 'cvr-cov--lg') : '<span class="cvr-cov--lg cvr-cov-empty">—</span>'}
          <div class="cvr-hero-txt">
            <div class="cvr-hero-l">Call coverage</div>
            <div class="cvr-hero-s">${hasQ
              ? `average of ${r.quality_n} first-round JD${r.quality_n === 1 ? '' : 's'}`
              : 'no scored JDs in this period'}</div>
          </div>
        </div>
        <div class="cvr-mcard-split">${split}</div>
        ${stats ? `<ul class="cvr-reasons-list">${stats}</ul>` : ''}
        ${checklist ? `<p class="cvr-reasons-cap">Flagged by the sales lead</p>
                       <ul class="cvr-reasons-list">${checklist}</ul>` : ''}
        ${chips ? `<div class="cvr-mchips">${chips}</div>` : ''}
      </article>`;
  }

  window.JdReviewCards = { card };
})();
