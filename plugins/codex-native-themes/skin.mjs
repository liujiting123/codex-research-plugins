// Shared by the real runtime and the preview fixture. All inputs are validated locally.
export const STYLE_ID = "codex-integrated-skin-style";
export const BACKDROP_ID = "codex-integrated-skin-backdrop";
export const ACTIVE_CLASS = "codex-integrated-skin";
export const APP_STYLE_ID = "codex-integrated-app-theme-style";
const SKIN_REVISION = "2026-10-03-reader-theme-2";
export const SELECTORS = {
  main: "main[data-app-shell-main-surface],main[class*='_MainContentSurface_']",
  // The responsive-sidebar attribute also belongs to the full window frame.
  sidebar: "aside.app-shell-left-panel,aside[data-app-shell-responsive-sidebar]",
  composer: "[data-composer-surface-variant][data-composer-radius-variant],[class*='_ComposerLayoutRoot_']",
  header: "[data-app-shell-titlebar],[data-app-shell-main-titlebar],[data-app-shell-page-header]",
};

function channels(hex) { return [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16)); }
function wash(hex, opacity) { return `rgba(${channels(hex).join(",")},${opacity})`; }
function mix(a, b, weight) {
  return "#" + channels(a).map((v, i) => Math.round(v * (1 - weight) + channels(b)[i] * weight).toString(16).padStart(2, "0")).join("");
}
function wallpaperBackground(config) {
  const n = config.native.theme, o = config.options, dark = config.native.variant === "dark";
  return o.wallpaper.kind === "image" ? `url("${o.wallpaper.dataUrl}")` :
    o.wallpaper.kind === "ambient" ? `radial-gradient(ellipse at 8% 10%,${wash(n.accent, dark ? .65 : .35)},transparent 58%),radial-gradient(ellipse at 90% 95%,${wash(mix(n.accent, "#5dd5ce", .55), dark ? .42 : .27)},transparent 62%),linear-gradient(145deg,${n.surface},${mix(n.surface, n.accent, .18)})` : "none";
}

export function buildSkinCss(config) {
  const n = config.native.theme, o = config.options, tokens = config.tokens || {};
  const dark = config.native.variant === "dark", root = `:root.${ACTIVE_CLASS}`;
  const layer = mix(n.surface, n.ink, dark ? .055 : .025);
  const t = (key, fallback) => tokens[`--dsw-${key}`] || fallback;
  const opacity = o.material === "flat" ? 1 : o.canvasOpacity;
  const canvas = wash(n.surface, o.wallpaper.kind === "none" ? 1 : opacity);
  const sidebar = wash(n.surface, o.material === "flat" ? 1 : o.sidebarOpacity);
  const composer = wash(layer, o.material === "flat" ? 1 : o.composerOpacity);
  const footerSurface = o.material === "flat" || o.wallpaper.kind === "none" ? canvas : "transparent";
  const border = t("alias-border-l1", wash(n.ink, .12));
  const borderHeavy = t("alias-border-l2", wash(n.ink, .20));
  const secondary = t("alias-label-secondary", wash(n.ink, .68));
  const tertiary = t("alias-label-tertiary", wash(n.ink, .45));
  const hover = wash(n.accent, .12), active = wash(n.accent, .20);
  const backdrop = wallpaperBackground(config);
  const blur = o.material === "flat" ? 0 : o.glassBlur;
  const declarations = {};
  const set = (keys, value) => keys.split(" ").forEach(k => declarations[k] = value);
  set("--bg-primary --color-surface-canvas --color-token-main-surface-primary --color-token-bg-primary --color-background-primary-surface", canvas);
  set("--bg-secondary --color-surface-secondary --color-token-main-surface-secondary --color-token-bg-secondary", wash(layer, .86));
  set("--bg-tertiary --color-surface-tertiary --color-token-main-surface-tertiary --color-token-bg-tertiary", mix(layer, n.ink, .06));
  set("--bg-elevated-primary --bg-elevated-secondary --color-surface-elevated --color-surface-elevated-secondary --color-surface-card --color-surface --color-background-panel --color-token-menu-background --color-token-dropdown-background --color-token-editor-widget-background", layer);
  set("--color-token-sidebar-surface-primary --color-token-sidebar-surface-secondary --color-token-side-bar-background --color-token-title-bar-active-background --color-token-title-bar-inactive-background", sidebar);
  set("--color-background-composer-primary --color-background-composer-surface --color-background-composer-action-bar --composer-background-color", composer);
  set("--text-primary --color-text --color-text-primary --color-text-emphasis --color-text-prose --color-token-text-primary --color-text-primary-surface --color-text-composer-primary --color-token-editor-foreground --color-token-terminal-foreground --color-token-side-bar-foreground", n.ink);
  set("--text-secondary --color-text-secondary --color-token-text-secondary --color-token-description-foreground --color-text-toolbar-action", secondary);
  set("--text-tertiary --text-quaternary --color-text-tertiary --color-token-text-tertiary --color-text-disabled", tertiary);
  set("--border-default --border-light --border-subtle --color-border --color-border-subtle --color-token-border --color-token-border-default --color-token-border-light --color-border-primary-surface", border);
  set("--border-heavy --color-border-strong --color-token-border-heavy --color-border-overlay", borderHeavy);
  set("--color-text-link --color-token-text-link-foreground --text-link --color-background-accent-solid --color-token-button-background --color-token-focus-border --color-text-discovery", n.accent);
  set("--color-background-user-message --color-background-user-message-compact --color-background-other-user-message", t("specific-bubble", layer));
  set("--color-text-user-message", n.ink);
  set("--color-background-text-selection --color-token-editor-selection-background --color-token-terminal-selection-background", wash(n.accent, .28));
  set("--color-background-button-outline-hover --color-token-list-hover-background", hover);
  set("--color-token-list-active-selection-background --color-token-list-inactive-selection-background", active);
  set("--color-token-text-code-block-background --color-token-text-preformat-background --color-token-editor-background --color-token-terminal-background", t("alias-markdown-code-block", layer));
  set("--color-token-diff-editor-inserted-text-background --color-token-diff-editor-inserted-line-background", wash(n.semanticColors.diffAdded, .16));
  set("--color-token-diff-editor-removed-text-background --color-token-diff-editor-removed-line-background", wash(n.semanticColors.diffRemoved, .16));
  const vars = Object.entries(declarations).map(([k, v]) => `${k}:${v} !important;`).join("\n");
  const scoped = selectors => selectors.split(",").map(s => `${root} ${s}`).join(",");
  const footer = `${root} .thread-scroll-container > .pointer-events-none.absolute.inset-x-0:has([data-codex-composer-root][data-composer-placement="thread"])`;
  return `
${root}{${vars}color-scheme:${config.native.variant};background:${n.surface} !important;color:${n.ink} !important;}
${root} body{background:transparent !important;isolation:isolate;}
${root} #root,${root} [data-app-shell-workspace-layout],${root} [data-app-shell-frame]{background:transparent !important;}
${root} #${BACKDROP_ID}{position:fixed;inset:-${o.wallpaperBlur * 2}px;z-index:-1;pointer-events:none;background-color:${n.surface};background-image:${backdrop};background-size:${o.wallpaperFit};background-position:center;background-repeat:no-repeat;filter:blur(${o.wallpaperBlur}px);opacity:${o.wallpaperOpacity};}
${scoped(SELECTORS.main)}{background:${canvas} !important;}
${scoped(SELECTORS.sidebar)}{background:${sidebar} !important;backdrop-filter:blur(${blur}px) saturate(${o.material === "liquid" ? 145 : 110}%);border-color:${border} !important;}
${scoped(SELECTORS.header)}{background:${wash(n.surface, opacity)} !important;backdrop-filter:blur(${blur}px);border-color:${border} !important;}
${scoped(SELECTORS.composer)}{background:${composer} !important;border:1px solid ${borderHeavy} !important;backdrop-filter:blur(${blur}px) saturate(${o.material === "liquid" ? 145 : 110}%);box-shadow:${o.material === "liquid" ? `inset 0 1px 0 ${wash(n.ink, .12)},0 8px 30px rgba(0,0,0,.12)` : "0 5px 24px rgba(0,0,0,.08)"} !important;}
/* The thread footer paints a separate fill and fade behind the composer. */
${footer},${footer} > .pointer-events-none.absolute.inset-x-0{background:${footerSurface} !important;}
${root} .thread-scroll-container .pointer-events-none.sticky.bottom-0 > .pointer-events-none.absolute.inset-x-0.bg-gradient-to-t.from-surface{--color-surface:${footerSurface} !important;--color-surface-secondary:${footerSurface} !important;}
${root} [role="menu"],${root} [role="dialog"]{background:${wash(layer, .97)} !important;border-color:${borderHeavy} !important;color:${n.ink} !important;backdrop-filter:blur(${blur}px);}
${root} [data-local-conversation-user-anchor] [class*="rounded"],${root} [data-message-author-role="user"] [class*="rounded"]{background:${t("specific-bubble", composer)} !important;border-color:${border} !important;}
${root} ::selection{background:${wash(n.accent, .30)};}
/* In 26.928 this attribute also marks the ENTIRE chat container. Only touch its paint. */
${root} [data-app-shell-main-content-top-fade]{--app-shell-main-content-top-fade-color:transparent;}
${root} [data-app-shell-main-content-top-fade]:empty{background:transparent !important;}
${root} ::-webkit-scrollbar-thumb{background:${t("alias-scrollbar-bg-l1", wash(n.ink, .18))} !important;border-radius:8px;}
${root} ::-webkit-scrollbar-thumb:hover{background:${t("alias-scrollbar-hover-l1", wash(n.ink, .30))} !important;}
`;
}

export function applyExpression(config) {
  const css = buildSkinCss(config);
  return `(() => {
    const config = ${JSON.stringify({themeId: config.themeId, fingerprint: config.fingerprint})};
    const root = document.documentElement;
    if (!document.body || !document.getElementById('root')) return {applied:false,reason:'renderer-not-ready'};
    let style = document.getElementById(${JSON.stringify(STYLE_ID)});
    if (!style) {style=document.createElement('style');style.id=${JSON.stringify(STYLE_ID)};document.head.append(style);}
    if (style.dataset.fingerprint!==config.fingerprint || style.textContent!==${JSON.stringify(css)}) {
      style.textContent=${JSON.stringify(css)};style.dataset.fingerprint=config.fingerprint;
    }
    style.dataset.skinRevision=${JSON.stringify(SKIN_REVISION)};
    let backdrop=document.getElementById(${JSON.stringify(BACKDROP_ID)});
    if (!backdrop) {backdrop=document.createElement('div');backdrop.id=${JSON.stringify(BACKDROP_ID)};backdrop.setAttribute('aria-hidden','true');document.body.prepend(backdrop);}
    root.classList.add(${JSON.stringify(ACTIVE_CLASS)});
    root.dataset.codexIntegratedSkin=config.themeId;
    const anchors = ${JSON.stringify(SELECTORS)};
    const compatibility=Object.fromEntries(Object.entries(anchors).map(([key,selector])=>[key,!!document.querySelector(selector)]));
    return {applied:true,themeId:config.themeId,compatibility};
  })()`;
}

export function statusExpression(fingerprint) {
  return `(() => {
    const style=document.getElementById(${JSON.stringify(STYLE_ID)});
    if (!style || style.dataset.fingerprint!==${JSON.stringify(fingerprint)} ||
        style.dataset.skinRevision!==${JSON.stringify(SKIN_REVISION)} ||
        !document.getElementById(${JSON.stringify(BACKDROP_ID)}) ||
        !document.documentElement.classList.contains(${JSON.stringify(ACTIVE_CLASS)})) return {applied:false};
    const anchors=${JSON.stringify(SELECTORS)};
    return {applied:true,compatibility:Object.fromEntries(Object.entries(anchors).map(([key,selector])=>[key,!!document.querySelector(selector)]))};
  })()`;
}

export const PAUSE_EXPRESSION = `(() => {
  document.getElementById(${JSON.stringify(STYLE_ID)})?.remove();
  document.getElementById(${JSON.stringify(BACKDROP_ID)})?.remove();
  document.documentElement.classList.remove(${JSON.stringify(ACTIVE_CLASS)});
  delete document.documentElement.dataset.codexIntegratedSkin;
  return {removed:true};
})()`;

function appColor(value, fallback, surface) {
  if (typeof value !== "string") return fallback;
  if (/^#[\da-f]{6}$/i.test(value)) return value;
  const match = value.match(/^rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)$/);
  if (!match) return fallback;
  const alpha = match[4] === undefined ? 1 : Number(match[4]);
  return "#" + channels(surface).map((base, i) => Math.round(base * (1 - alpha) + Number(match[i + 1]) * alpha).toString(16).padStart(2, "0")).join("");
}

export function buildAppTheme(config) {
  const n = config.native.theme, tokens = config.tokens || {};
  const o = config.options;
  const glass = o.material !== "flat" && o.wallpaper.kind !== "none";
  const backdrop = wallpaperBackground(config);
  const layer = mix(n.surface, n.ink, config.native.variant === "dark" ? .055 : .025);
  const secondary = appColor(tokens["--dsw-alias-label-secondary"], mix(n.surface, n.ink, .68), n.surface);
  const border = appColor(tokens["--dsw-alias-border-l1"], mix(n.surface, n.ink, .12), n.surface);
  const variables = {
    "--color-background-primary": n.surface,
    "--color-background-secondary": layer,
    "--color-background-tertiary": mix(layer, n.ink, .06),
    "--color-text-primary": n.ink,
    "--color-text-secondary": secondary,
    "--color-border-primary": border,
    "--color-border-secondary": border,
    "--color-accent": n.accent,
    "--color-text-link": n.accent,
    "--bg-primary": n.surface,
    "--bg-secondary": layer,
    "--text-primary": n.ink,
    "--text-secondary": secondary,
    "--border-default": border,
    // Opt-in reader tokens keep other plugin surfaces unchanged.
    "--paper-reader-background-image": backdrop,
    "--paper-reader-background-size": o.wallpaperFit,
    "--paper-reader-background-opacity": String(o.wallpaperOpacity),
    "--paper-reader-background-filter": `blur(${o.wallpaperBlur}px)`,
    "--paper-reader-canvas-background": wash(n.surface, glass ? o.canvasOpacity : 1),
    "--paper-reader-panel-background": wash(n.surface, glass ? o.canvasOpacity : 1),
    "--paper-reader-glass-blur": `blur(${glass ? o.glassBlur : 0}px)`,
    "--paper-reader-paper-opacity": glass ? "0" : "1",
  };
  return {enabled: true, theme: config.native.variant, styles: {variables}, fingerprint: `${config.fingerprint}:${SKIN_REVISION}`};
}

export function appThemeExpression(context) {
  // Already-open readers can still have the earlier cached accent alias.
  const css = context.enabled ? `:root{color-scheme:${context.theme} !important;${Object.entries(context.styles.variables).map(([key, value]) => `${key}:${value} !important;`).join("")}}:root:has(#paper-palette){--accent:var(--color-accent) !important;}` : "";
  return `(() => {
    const context=${JSON.stringify(context)},css=${JSON.stringify(css)},styleId=${JSON.stringify(APP_STYLE_ID)};
    let documents=0;
    const apply=(doc) => {
      if(!doc?.body)return;
      const win=doc.defaultView,root=doc.documentElement;
      let style=doc.getElementById(styleId);
      if(context.enabled){
        if(!win.__CODEX_SKIN_THEME_BACKUP__)win.__CODEX_SKIN_THEME_BACKUP__={theme:root.getAttribute('data-theme'),dark:root.classList.contains('dark')};
        if(!style){style=doc.createElement('style');style.id=styleId;doc.head.append(style);}
        const changed=style.textContent!==css||win.__CODEX_SKIN_THEME__?.fingerprint!==context.fingerprint||root.dataset.theme!==context.theme;
        if(changed){
          style.textContent=css;
          win.__CODEX_SKIN_THEME__=context;
          root.classList.toggle('dark',context.theme==='dark');
          root.dataset.theme=context.theme;
          win.dispatchEvent(new win.CustomEvent('codex:theme-changed',{detail:context}));
        }
        documents++;
      }else{
        style?.remove();
        const previous=win.__CODEX_SKIN_THEME_BACKUP__;
        if(previous){
          const theme=win.openai?.theme;
          root.classList.toggle('dark',theme?theme==='dark':previous.dark);
          if(theme||previous.theme!==null)root.dataset.theme=theme||previous.theme;else delete root.dataset.theme;
          delete win.__CODEX_SKIN_THEME_BACKUP__;
          delete win.__CODEX_SKIN_THEME__;
          win.dispatchEvent(new win.CustomEvent('codex:theme-changed',{detail:context}));
        }
        documents++;
      }
      for(const frame of doc.querySelectorAll('iframe')){try{if(frame.contentDocument)apply(frame.contentDocument);}catch{}}
    };
    apply(document);
    return {applied:context.enabled&&documents>0,removed:!context.enabled&&documents>0,documents};
  })()`;
}
