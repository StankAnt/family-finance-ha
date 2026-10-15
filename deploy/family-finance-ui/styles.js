import { tokens } from "./tokens.js";

export const styles = `${tokens}
  :host { display:block; color:var(--ff-ink); font-family:var(--primary-font-family,system-ui,sans-serif); }
  * { box-sizing:border-box; }
  .app { max-width:1320px; margin:0 auto; padding:clamp(16px,3vw,36px); background:var(--ff-canvas); min-height:calc(100vh - 110px); }
  .mast { background:linear-gradient(115deg,#132e49,#176772); color:#fff; border-radius:24px; padding:clamp(22px,4vw,38px); box-shadow:0 16px 35px #0e324024; }
  .mast-top { display:flex; justify-content:space-between; align-items:start; gap:20px; flex-wrap:wrap; }
  .eyebrow { text-transform:uppercase; font-size:.7rem; letter-spacing:.14em; opacity:.8; font-weight:700; }
  h1 { font-size:clamp(1.7rem,3vw,2.5rem); line-height:1.12; margin:8px 0; letter-spacing:-.03em; }
  .mast p { margin:0; color:#d3e7ec; max-width:650px; }
  .source-control { min-width:180px; color:#e0f0f1; }
  .source-control select { color:#16364b; background:#fff; }
  .surface button + button { margin-left:8px; }
  .period-control { display:grid; grid-template-columns:auto 40px 170px 40px; align-items:center; gap:8px; }
  .period-control label { color:#e0f0f1; font-weight:600; font-size:.85rem; }
  .period-control input { width:170px; }
  .period-control input { color:#16364b; background:#fff; font-size:1rem; }
  .period-control button { color:#fff; border-color:#ffffff66; background:#ffffff18; }
  .nav { display:flex; gap:7px; overflow-x:auto; padding:18px 0 20px; }
  button { font:inherit; border:1px solid var(--ff-border); border-radius:11px; background:var(--ff-surface); color:inherit; padding:10px 14px; cursor:pointer; transition:background .15s,transform .15s; }
  button:hover:not(:disabled) { transform:translateY(-1px); background:var(--secondary-background-color,#eef4f6); }
  button:focus-visible, a:focus-visible, select:focus-visible, input:focus-visible, summary:focus-visible { outline:3px solid var(--ff-focus); outline-offset:2px; }
  button:disabled { opacity:.55; cursor:wait; }
  button.primary { background:var(--ff-accent); border-color:var(--ff-accent); color:white; font-weight:700; }
  button.primary:hover:not(:disabled) { background:var(--ff-accent-dark); }
  .nav a { white-space:nowrap; border:0; border-radius:11px; background:transparent; padding:11px 17px; font-weight:650; color:inherit; text-decoration:none; }
  .nav a:hover, .nav a:focus-visible { background:var(--ff-accent-soft); }
  .nav a.active { color:var(--ff-accent-dark); background:var(--ff-accent-soft); }
  .message { padding:12px 16px; margin-bottom:16px; border-radius:10px; background:#fff0ed; color:#9a2d22; border:1px solid #f7c9be; }
  .message.success { background:#e8f7ef; color:#156744; border-color:#bae8d0; }
  .message[hidden] { display:none; }
  .content { display:grid; gap:18px; }
  .section-head { display:flex; align-items:end; justify-content:space-between; gap:12px; flex-wrap:wrap; margin:3px 0; }
  h2 { margin:0; font-size:1.45rem; letter-spacing:-.02em; }
  h3 { margin:0 0 8px; font-size:1.05rem; }
  .muted { color:var(--ff-muted); font-size:.9rem; line-height:1.45; }
  .surface,.metric,.tx,.section { background:var(--ff-surface); border:1px solid var(--ff-border); border-radius:var(--ff-radius-lg); box-shadow:var(--ff-shadow); }
  .surface,.section { padding:20px; }
  .metrics { display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:12px; }
  .outgoing-summary { border-color:#91cbd0; }
  .outgoing-summary .metrics { grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); margin-top:12px; }
  .outgoing-equation { margin:14px 0 0; }
  .metric { padding:20px; border-top:4px solid var(--ff-accent); }
  .metric.warm { border-top-color:var(--ff-warning); }
  .metric.soft { border-top-color:#9ca4b5; }
  .metric-title { font-size:.85rem; color:var(--secondary-text-color,#627386); font-weight:650; }
  .metric-value { font-size:clamp(1.35rem,2.1vw,1.8rem); margin-top:10px; font-weight:750; font-variant-numeric:tabular-nums; }
  .metric-note { margin-top:8px; font-size:.8rem; color:var(--secondary-text-color,#738292); line-height:1.4; }
  .banner { padding:14px 17px; border-radius:13px; background:#fff5e7; border:1px solid #f3d6a9; color:#68491d; }
  .banner.good { background:#e7f6ef; border-color:#b8e4cf; color:#205b43; }
  .split { display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:16px; }
  .chart-section { display:grid; gap:12px; }
  .chart-section .section-head { align-items:baseline; }
  .chart-section .section-head p { margin:0; max-width:750px; }
  .chart-card { min-width:0; }
  .chart-head { display:grid; gap:12px; align-items:start; }
  .chart-head h3 { margin:0; }
  .chart-filters { display:flex; gap:10px; flex-wrap:wrap; }
  .chart-filters label { min-width:170px; max-width:240px; }
  .chart-layout { display:grid; grid-template-columns:minmax(170px,220px) minmax(0,1fr); align-items:start; gap:24px; margin-top:20px; }
  .donut { width:min(100%,220px); aspect-ratio:1; border-radius:50%; display:grid; place-items:center; cursor:crosshair; }
  .donut-center { width:62%; aspect-ratio:1; border-radius:50%; display:flex; flex-direction:column; align-items:center; justify-content:center; text-align:center; background:var(--card-background-color,#fff); padding:8px; }
  .donut-center strong { font-size:clamp(.9rem,1.6vw,1.2rem); font-variant-numeric:tabular-nums; }
  .donut-center small { color:var(--secondary-text-color,#657789); max-width:100%; font-size:.72rem; line-height:1.2; overflow-wrap:anywhere; }
  .chart-legend { display:grid; gap:8px; }
  .chart-legend-row { display:grid; grid-template-columns:12px minmax(0,1fr) auto; gap:9px; align-items:center; font-size:.84rem; border-bottom:1px solid var(--divider-color,#e3e9ed); padding:5px 0; }
  .chart-legend-row.is-link { cursor:pointer; }
  .chart-legend-row.is-link:not(.is-active):hover, .chart-legend-row.is-link:not(.is-active):focus-visible { background:var(--secondary-background-color,#eef4f6); border-radius:6px; }
  .chart-legend-row.is-link:focus-visible { outline:3px solid #46b6c2; outline-offset:2px; }
  .chart-legend-row.is-active, .chart-rest-summary.is-active { background:#e8f4f4; background:color-mix(in srgb,var(--chart-accent) 18%,white); box-shadow:inset 4px 0 var(--chart-accent); outline:2px solid var(--chart-accent); outline-offset:-2px; border-radius:6px; font-weight:700; }
  .chart-legend-row strong { font-variant-numeric:tabular-nums; }
  .chart-legend-value { display:flex; flex-direction:column; align-items:flex-end; white-space:nowrap; }
  .chart-legend-value small { color:var(--secondary-text-color,#657789); }
  .chart-rest { margin:0; }
  .chart-rest-summary { display:grid; grid-template-columns:12px minmax(0,1fr) auto; gap:9px; align-items:center; padding:10px 0; border-bottom:1px solid var(--divider-color,#e3e9ed); list-style:none; font-size:.84rem; }
  .chart-rest-summary::-webkit-details-marker { display:none; }
  .chart-rest-summary strong { color:var(--primary-text-color,#17263d); font-variant-numeric:tabular-nums; white-space:nowrap; }
  .chart-rest .chart-legend-row { padding-left:21px; }
  .chart-swatch { width:12px; height:12px; border-radius:3px; }
  .list { display:grid; gap:9px; margin-top:14px; }
  .list-row { display:flex; justify-content:space-between; gap:12px; padding:8px 0; border-top:1px solid var(--divider-color,#e9edf0); }
  .list-row strong { font-variant-numeric:tabular-nums; white-space:nowrap; }
  .toolbar { display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; align-items:end; }
  .toolbar-actions { display:flex; align-items:end; gap:12px; flex-wrap:wrap; }
  .review-head { display:grid; grid-template-columns:minmax(0,1fr); align-items:start; gap:18px; min-width:0; }
  .review-head .toolbar-actions { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); align-items:end; width:100%; min-width:0; }
  .review-head .toolbar-actions > label { width:100%; max-width:none; min-width:0; }
  .review-head .review-search { width:100%; grid-column:span 2; }
  .review-head .review-project { grid-column:span 2; }
  .review-search { width:min(100%,520px); min-width:0; }
  .review-search-controls { display:flex; align-items:center; gap:7px; }
  .review-search-controls input { min-width:0; flex:1; }
  .review-search-controls button { min-height:42px; white-space:nowrap; }
  .tx-list { display:grid; gap:18px; }
  .transaction-list-item { margin:0; min-width:0; background:var(--card-background-color,#fff); border:1px solid var(--divider-color,#e3e9ed); border-radius:14px; overflow:hidden; }
  .transaction-list-summary { display:grid; grid-template-columns:100px minmax(0,1fr) auto; gap:14px; align-items:center; padding:15px 18px; list-style:none; color:var(--primary-text-color,#17263d); }
  .transaction-list-summary::-webkit-details-marker { display:none; }
  .transaction-list-summary:hover { background:var(--secondary-background-color,#eef4f6); }
  .transaction-list-summary:focus-visible { outline:3px solid #46b6c2; outline-offset:-3px; }
  .transaction-list-main { min-width:0; display:grid; gap:3px; }
  .transaction-list-main strong { overflow:hidden; white-space:nowrap; text-overflow:ellipsis; font-weight:600; }
  .transaction-list-main small,.transaction-list-date { color:var(--secondary-text-color,#657789); font-size:.83rem; }
  .transaction-list-main small { overflow:hidden; white-space:nowrap; text-overflow:ellipsis; }
  .transaction-list-amount { white-space:nowrap; font-variant-numeric:tabular-nums; }
  .transaction-list-amount.in { color:#11705d; }
  .transaction-list-item[open] > .transaction-list-summary { border-bottom:1px solid var(--divider-color,#e3e9ed); }
  .transaction-list-item.is-target, .tx.is-target { outline:2px solid var(--ff-accent); outline-offset:-2px; }
  .transaction-list-item > .tx { border:0; border-radius:0; box-shadow:none; }
  .tx { padding:24px; overflow:visible; }
  .tx-head { display:grid; grid-template-columns:40px minmax(0,1fr) auto; align-items:start; gap:14px; }
  .tx-menu { position:relative; margin:0; z-index:2; }
  .tx-menu summary { display:grid; place-items:center; width:36px; height:36px; border:1px solid var(--divider-color,#dce3e9); border-radius:10px; color:inherit; background:var(--card-background-color,#fff); font-size:1.4rem; line-height:1; list-style:none; }
  .tx-menu summary::-webkit-details-marker { display:none; }
  .tx-menu summary:focus-visible { outline:3px solid #46b6c2; outline-offset:2px; }
  .tx-menu-panel { position:absolute; top:42px; left:0; min-width:260px; max-width:min(320px,85vw); padding:8px; background:var(--card-background-color,#fff); border:1px solid var(--divider-color,#dce3e9); border-radius:12px; box-shadow:0 12px 28px #12304a24; }
  .tx-menu-panel button { width:100%; text-align:left; }
  .tx-date { font-size:.86rem; color:var(--secondary-text-color,#657789); }
  .tx-amount { font-weight:750; font-size:1.28rem; font-variant-numeric:tabular-nums; }
  .tx-amount.in { color:#11705d; }
  .memo { white-space:pre-wrap; overflow-wrap:anywhere; margin:18px 0 20px 54px; line-height:1.5; }
  .suggestion { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:12px; padding:13px; background:#e9f5f5; border:1px solid #c1e0e0; border-radius:12px; margin-bottom:14px; }
  .suggestion strong { color:#195764; }
  .form-grid,.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; align-items:end; }
  label { display:flex; flex-direction:column; gap:6px; font-size:.84rem; font-weight:650; }
  input,select { width:100%; min-height:42px; padding:9px 11px; border:1px solid var(--divider-color,#bccbd4); border-radius:9px; background:var(--card-background-color,#fff); color:var(--primary-text-color,#17263d); font:inherit; }
  input[type=checkbox] { width:auto; min-height:auto; }
  .check { flex-direction:row; align-items:center; }
  .type-help { grid-column:1/-1; margin:-3px 0 0; min-height:1.2em; }
  .advanced-type { grid-column:1/-1; margin:2px 0 0; }
  .advanced-type summary { width:max-content; max-width:100%; font-size:.86rem; }
  .advanced-type label { max-width:390px; margin-top:12px; }
  .actions { display:flex; align-items:center; gap:9px; }
  .pager { display:flex; align-items:center; gap:8px; }
  .pair-picker { border-color:#80c5c9; background:#f2fbfa; }
  .pair-picker button { margin:12px 8px 0 0; }
  .pair-picker .list-row span { overflow-wrap:anywhere; }
  .account-list { display:grid; grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); gap:10px; margin:12px 0 20px; }
  .account-row { display:grid; gap:6px; padding:16px; border:1px solid var(--divider-color,#e3e9ed); border-radius:12px; }
  .account-row span { font-size:1.25rem; font-weight:750; font-variant-numeric:tabular-nums; }
  .account-row small { color:var(--secondary-text-color,#657789); }
  .mortgage-guide { margin-top:18px; padding-top:18px; border-top:1px solid var(--divider-color,#e3e9ed); }
  .empty { padding:35px 20px; text-align:center; }
  .section { margin:0; }
  details { margin-top:14px; }
  summary { cursor:pointer; color:#08727e; font-weight:650; }
  .onboarding { display:grid; gap:18px; }
  .onboarding > h3,.onboarding > p { margin:0; }
  .onboarding-step { margin:0; padding:16px 18px; border:1px solid var(--ff-border); border-radius:12px; background:var(--ff-canvas); min-width:0; }
  .onboarding-step > summary { font-size:.98rem; }
  .onboarding-step[open] > summary { margin-bottom:16px; }
  .onboarding-step > p { max-width:76ch; margin:0 0 16px; }
  .onboarding-field,.onboarding-step .setup-form { display:grid; gap:8px; max-width:760px; }
  .onboarding-field { margin:14px 0; }
  .onboarding-step .setup-form { gap:14px; }
  .onboarding-step .setup-form > label { margin-bottom:-8px; }
  .onboarding-step .setup-form > button { justify-self:start; }
  .onboarding-actions { display:flex; flex-wrap:wrap; align-items:center; gap:10px; margin:14px 0; }
  .onboarding .onboarding-actions button + button { margin-left:0; }
  .onboarding-step input[type=file] { max-width:760px; height:auto; }
  .onboarding-step .auth-link { max-width:760px; overflow-wrap:anywhere; }
  .onboarding-step textarea { display:block; width:min(100%,760px); margin-top:12px; }
  .onboarding-consent { display:flex; flex-direction:row; align-items:center; gap:10px; margin:16px 0; font-weight:500; }
  .onboarding-consent input { flex:none; margin:0; }
  @media(max-width:900px) { .review-head .toolbar-actions { grid-template-columns:repeat(2,minmax(0,1fr)); } }
  @media(max-width:600px) { .review-head .toolbar-actions { grid-template-columns:1fr; } .review-head .review-search,.review-head .review-project { grid-column:auto; } .review-search-controls { display:grid; grid-template-columns:minmax(0,1fr) auto; } .review-search-controls input { grid-column:1/-1; width:100%; } .transaction-list-summary { grid-template-columns:minmax(0,1fr) auto; gap:5px 10px; padding:12px; } .transaction-list-date { grid-column:1/-1; } .app { padding:12px; } .tx,.surface,.section { padding:16px; } .tx-head { gap:8px; } .tx-amount { font-size:1.05rem; } .memo { margin-left:0; } .metric { padding:16px; } .chart-layout { grid-template-columns:1fr; justify-items:center; } .chart-legend { width:100%; } .chart-filters,.chart-filters label { width:100%; max-width:none; } .period-control { width:100%; grid-template-columns:auto 40px minmax(120px,1fr) 40px; } .period-control input { width:100%; } .onboarding-step { padding:14px; } .onboarding-actions { align-items:stretch; } .onboarding-actions button { width:100%; } }
`;
