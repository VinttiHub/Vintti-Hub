const norm = (value) => (value || '').toString().toLowerCase().trim();

export function normalizeStage(stage) {
  const value = norm(stage);
  if (/closed?[_\s-]?won|close[_\s-]?win/.test(value)) return 'won';
  if (/closed?[_\s-]?lost|close[_\s-]?lost/.test(value)) return 'lost';
  if (/(sourc|interview|negotiat|deep\s?dive)/.test(value)) return 'pipeline';
  return 'other';
}

export function isActiveHire(hire = {}) {
  const status = norm(hire.status);
  if (status === 'active') return true;
  if (status === 'inactive') return false;

  const endDate = (hire.end_date || '').toString().trim().toLowerCase();
  if (!endDate || endDate === 'null' || endDate === 'none' || endDate === 'undefined' || endDate === '0000-00-00') {
    return true;
  }
  return false;
}

export function hasBuyout(hire = {}) {
  const amount = hire.buyout_dolar;
  const range = hire.buyout_daterange;
  const hasAmount = amount !== null && amount !== undefined && String(amount).trim() !== '';
  const hasRange = range !== null && range !== undefined && String(range).trim() !== '';
  return hasAmount || hasRange;
}

export function deriveStatusFrom(opps = [], hires = []) {
  const stages = (opps || []).map((opp) => normalizeStage(opp.opp_stage || opp.stage));
  const hasOpps = stages.length > 0;
  const hasPipeline = stages.some((stage) => stage === 'pipeline');
  const allLost = hasOpps && stages.every((stage) => stage === 'lost');

  const hasCandidates = Array.isArray(hires) && hires.length > 0;
  const anyActiveCandidate = hasCandidates && hires.some(isActiveHire);
  const hasBuyoutCandidate = Array.isArray(hires) && hires.some(hasBuyout);
  const allCandidatesInactive = hasCandidates && hires.every((hire) => !isActiveHire(hire));

  if (anyActiveCandidate || hasBuyoutCandidate) return 'Active Client';
  if (allCandidatesInactive) return 'Inactive Client';
  if (!hasOpps && !hasCandidates) return 'Lead';
  if (allLost && !hasCandidates) return 'Lead Lost';
  if (hasPipeline) return 'Lead in Process';
  if (!hasOpps && hasCandidates) return 'Inactive Client';
  return 'Lead in Process';
}

export function deriveContractFromHires(hires = []) {
  if (!Array.isArray(hires) || hires.length === 0) return null;
  let hasStaffing = false;
  let hasRecruitingOrBuyout = false;

  for (const hire of hires) {
    if (!hire || !isActiveHire(hire)) continue;
    const model = (hire.opp_model || '').toLowerCase();
    if (model.includes('staff')) hasStaffing = true;
    if (model.includes('recruit')) hasRecruitingOrBuyout = true;
    if (hasBuyout(hire)) hasRecruitingOrBuyout = true;

    if (hasStaffing && hasRecruitingOrBuyout) {
      return 'Mix';
    }
  }

  if (hasStaffing) return 'Staffing';
  if (hasRecruitingOrBuyout) return 'Recruiting';
  return null;
}
