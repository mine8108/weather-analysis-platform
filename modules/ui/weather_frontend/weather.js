export default function(component) {
  const {data, parentElement, setTriggerValue} = component;
  const root = parentElement.querySelector('.wc-root');
  root.replaceChildren();
  root.dataset.theme = data.theme || 'light';
  root.className = 'wc-root ' + (data.expanded ? 'wc-expanded' : 'wc-compact');
  const abort = new AbortController();
  const signal = abort.signal;
  const motions = [];
  const timers = new Set();
  let disposed = false;
  let dialogOpen = false;
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const hoverCapable = window.matchMedia('(hover: hover) and (pointer: fine)');
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = String(text);
    return node;
  };
  const icon = name => { const node = el('span', 'wc-icon', name); node.setAttribute('aria-hidden', 'true'); return node; };
  const button = (label, symbol, fn, cls = 'wc-action') => {
    const b = el('button', cls); b.type = 'button';
    if (symbol) b.append(icon(symbol));
    b.append(el('span', '', label));
    b.addEventListener('click', fn, {signal});
    return b;
  };
  const emit = (type, value = {}) => setTriggerValue('event', {
    type, ...value, event_id: (globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`)
  });
  const later = (fn, ms) => { const id = setTimeout(() => {timers.delete(id); if (!disposed) fn();}, ms); timers.add(id); return id; };
  const sceneUrl = scene => `${data.asset_base}/${scene}.jpg`;
  const stopAll = () => motions.forEach(m => m.stop());
  const titleBar = el('div', 'wc-toolbar');
  const titleGroup = el('div', 'wc-title-group');
  titleGroup.append(el('h2', 'wc-title', data.expanded ? '城市天气墙' : '城市天气'));
  titleGroup.append(el('span', 'wc-count', `${data.cards.length} 个关注城市`));
  if (data.demo) titleGroup.append(el('span', 'wc-badge', '预览示例'));
  titleBar.append(titleGroup);
  let search = null;
  if (data.expanded && data.cards.length) {
    const searchBox = el('label', 'wc-search'); searchBox.append(icon('search'));
    search = el('input'); search.type = 'search'; search.placeholder = '搜索已关注城市'; search.setAttribute('aria-label', '搜索已关注城市');
    searchBox.append(search); titleBar.append(searchBox);
  }
  if (data.expanded) {
    titleBar.append(button('管理城市', 'add_location_alt', () => emit('manage')));
    titleBar.append(button('刷新', 'refresh', () => emit('refresh')));
    titleBar.append(button('收起', 'expand_less', () => emit('toggle')));
  }
  root.append(titleBar);

  const dialog = el('dialog', 'wc-dialog');
  dialog.setAttribute('aria-label', '查看城市预报');
  const closeDialog = () => { dialog.close(); dialogOpen = false; };
  dialog.addEventListener('close', () => { dialogOpen = false; }, {signal});
  dialog.addEventListener('cancel', () => { dialogOpen = false; }, {signal});
  function openCity(city) {
    stopAll(); dialogOpen = true; dialog.replaceChildren();
    let days = 7;
    const close = button('关闭', 'close', closeDialog, 'wc-dialog-close'); close.setAttribute('aria-label', '关闭城市预报确认');
    dialog.append(close);
    const header = el('div', 'wc-dialog-header');
    const thumb = el('img', 'wc-dialog-thumb'); thumb.src = sceneUrl(city.scene); thumb.alt = ''; header.append(thumb);
    const info = el('div'); info.append(el('h2', 'wc-dialog-city', city.name));
    info.append(el('p', 'wc-dialog-description', city.coordinates));
    if (city.landmark) info.append(el('p', 'wc-dialog-landmark', `城市地标 · ${city.landmark.name}`));
    info.append(el('p', 'wc-dialog-description', `${city.temperature}  ${city.condition}  ·  今日 ${city.high_low}`)); header.append(info);
    dialog.append(header, el('h3', 'wc-dialog-question', `查看${city.name}未来几天的天气？`));
    dialog.append(el('p', 'wc-dialog-description', '确认后打开数值预报，自动带入该城市的位置。'));
    const periods = el('div', 'wc-periods'); periods.setAttribute('role', 'group'); periods.setAttribute('aria-label', '预报时段');
    const periodButtons = [];
    const dateText = el('div', 'wc-dialog-description');
    const refreshDates = () => {
      const start = new Date(data.today + 'T00:00:00Z'); const end = new Date(start); end.setUTCDate(end.getUTCDate() + days - 1);
      const fmt = date => `${date.getUTCMonth() + 1}月${date.getUTCDate()}日`;
      dateText.textContent = `${fmt(start)} — ${fmt(end)} · 北京时间 · ${days} 个自然日`;
      periodButtons.forEach((b, i) => b.setAttribute('aria-pressed', String([3, 7, 16][i] === days)));
    };
    [3, 7, 16].forEach(n => { const b = button(`${n} 天`, null, () => { days = n; refreshDates(); }, 'wc-period'); periodButtons.push(b); periods.append(b); });
    refreshDates(); dialog.append(periods, dateText);
    dialog.append(el('div', 'wc-dialog-meta', '数据来源  Open-Meteo · GFS\n较远时效的预报变化可能更大，请结合最新起报资料判断。'));
    const footer = el('div', 'wc-dialog-footer');
    footer.append(el('small', '', '确认前保留当前页面、筛选条件和已生成结果。'));
    footer.append(button('取消', null, closeDialog));
    footer.append(button('查看预报', 'arrow_forward', () => { closeDialog(); emit('confirm', {city_id: city.id, days}); }, 'wc-action primary'));
    dialog.append(footer); dialog.showModal();
  }

  const cardsContainer = el('div', data.expanded ? 'wc-grid' : 'wc-strip');
  const cards = [];
  function makeCard(city, i) {
    const card = el('button', 'wc-card' + (city.active ? ' active' : '')); card.type = 'button';
    card.dataset.scene = city.scene; card.dataset.night = String(!city.is_day); card.dataset.cityId = city.id; card.dataset.motion = 'static';
    card.setAttribute('aria-label', `${city.name}，${city.temperature}，${city.condition}。查看城市预报`);
    card.title = [city.name, city.coordinates, city.valid_at ? `天气有效时间 ${city.valid_at} ${city.timezone}` : '', city.stale ? '上次成功数据，刷新未成功' : 'Open-Meteo 模式天气'].filter(Boolean).join(' · ');
    const poster = el('img', 'wc-poster'); poster.src = sceneUrl(city.scene); poster.alt = ''; poster.decoding = 'async';
    poster.loading = i < 6 ? 'eager' : 'lazy'; card.append(poster);
    if (city.landmark && /^[a-z-]+\.webp$/.test(city.landmark.asset)) {
      card.dataset.landmark = city.landmark.id;
      const landmark = el('img', 'wc-landmark');
      landmark.src = `${data.asset_base}/landmarks/${city.landmark.asset}`;
      landmark.alt = ''; landmark.decoding = 'async'; landmark.loading = i < 6 ? 'eager' : 'lazy';
      landmark.addEventListener('error', () => { landmark.hidden = true; }, {once:true, signal});
      card.append(landmark);
      card.title += ` · 城市地标：${city.landmark.name}`;
    }
    let layerName = ['rain', 'thunder'].includes(city.scene) ? 'rain-layer' : city.scene === 'snow' ? 'snow-layer' : 'cloud-layer';
    const layer = el('img', 'wc-layer' + (layerName !== 'cloud-layer' ? ' particles' : '')); layer.src = `${data.asset_base}/${layerName}.png`; layer.alt = ''; layer.decoding = 'async'; card.append(layer);
    card.append(el('span', 'wc-tint'));
    const motionZone = el('span', 'wc-motion-zone'); motionZone.setAttribute('aria-hidden', 'true'); card.append(motionZone);
    const cityLine = el('span', 'wc-city-line'); cityLine.append(el('span', 'wc-city-name', city.name), el('span', 'wc-coordinates', city.coordinates)); card.append(cityLine);
    if (city.active) { const a = el('span', 'wc-active'); a.append(icon('check_circle'), el('span', '', '正在分析')); card.append(a); }
    const values = el('span', 'wc-main-values'); values.append(el('span', 'wc-temperature', city.temperature));
    const conditions = el('span', 'wc-conditions'); conditions.append(el('span', 'wc-condition', city.condition), el('span', 'wc-high-low', city.high_low)); values.append(conditions); card.append(values);
    const details = el('span', 'wc-detail');
    [['humidity_percentage', `湿度 ${city.humidity}`], ['air', city.wind], ['eco', city.aqi === '—' ? 'AQI —' : `AQI ${city.aqi}`]].forEach(([sym, text]) => { const d = el('span', 'wc-detail-item'); d.append(icon(sym), el('span', '', text)); details.append(d); });
    card.append(details);
    const arrow = el('span', 'wc-open'); arrow.append(icon('arrow_forward')); card.append(arrow);
    if (city.stale || city.aqi_stale) card.append(el('span', 'wc-stale', city.stale ? '天气为上次更新' : 'AQI 为上次更新'));
    card.addEventListener('click', () => openCity(city), {signal});
    cards.push({card, name: city.name});
    let animations = []; let visible = true; let hovered = false; let entryTimer = null; let settleTimer = null;
    function stop(smooth = false) {
      card.dataset.landmarkReveal = 'false';
      const settle = smooth && animations.length && !disposed && !reduced.matches && visible && !document.hidden && !dialogOpen;
      const current = settle ? [poster, layer].map(node => ({transform: getComputedStyle(node).transform, opacity: getComputedStyle(node).opacity})) : null;
      animations.forEach(a => a.cancel()); animations = [];
      if (entryTimer) {clearTimeout(entryTimer); timers.delete(entryTimer); entryTimer = null;}
      if (settleTimer) {clearTimeout(settleTimer); timers.delete(settleTimer); settleTimer = null;}
      card.dataset.motion = 'static';
      if (settle) {
        card.dataset.motion = 'settling';
        animations = [poster, layer].map((node, index) => node.animate([current[index], {
          transform: getComputedStyle(node).transform, opacity: getComputedStyle(node).opacity
        }], {duration: 180, easing: 'ease-out'}));
        settleTimer = later(() => {settleTimer = null; stop();}, 180);
      }
    }
    function play(kind) {
      if (disposed || reduced.matches || document.hidden || dialogOpen || !visible || !city.loaded) return;
      stop(); card.dataset.motion = kind;
      card.dataset.landmarkReveal = String(kind === 'hover' && hovered);
      const duration = kind === 'entry' ? 2100 : 5200;
      const opts = {duration, iterations: kind === 'entry' ? 1 : Infinity, easing: 'ease-in-out'};
      // Weather imagery moves independently. Text, card position and layout remain fixed.
      animations.push(poster.animate([{transform:'scale(1.015) translateX(0)'},{transform:'scale(1.035) translateX(-.6%)'},{transform:'scale(1.015) translateX(0)'}], opts));
      const particle = layerName !== 'cloud-layer';
      const peakOpacity = particle ? .36 : (city.scene === 'fog' ? .23 : .16);
      animations.push(layer.animate([
        {transform: particle ? 'translate(0,-5%)' : 'translateX(2%)', opacity: 0},
        {transform: particle ? 'translate(-1%,0)' : 'translateX(-1%)', opacity: peakOpacity, offset:.5},
        {transform: particle ? 'translate(-2%,6%)' : 'translateX(-4%)', opacity: 0}
      ], opts));
      if (kind === 'entry') entryTimer = later(() => {stop(); if (hovered) play('hover');}, duration);
    }
    motionZone.addEventListener('pointerenter', event => {
      hovered = event.pointerType === 'mouse' && hoverCapable.matches;
      if (hovered) { play('hover'); card.dataset.landmarkReveal = 'true'; }
    }, {signal});
    motionZone.addEventListener('pointerleave', () => { hovered = false; stop(true); }, {signal});
    const motion = {stop, enter: () => play('entry'), setVisible: value => {visible = value; if (!value) {hovered = false; stop();}}};
    motions.push(motion); return card;
  }
  data.cards.forEach((city, i) => cardsContainer.append(makeCard(city, i)));
  if (!data.cards.length) {
    const empty = el('div', 'wc-empty'); empty.append(el('span', '', '添加关注城市，随时查看天气并进入预报分析。'), button('添加城市', 'add_location_alt', () => emit('manage'))); root.append(empty);
  } else if (data.expanded) {
    root.append(cardsContainer);
    const note = el('div', 'wc-footnote'); note.append(el('span', '', 'Open-Meteo 模式天气 · 卡片时间按地点时区显示 · 场景为天气与城市插画'));
    note.append(el('span', '', '点击城市查看预报 · 悬停天气图像发现地标彩蛋')); root.append(note);
  } else {
    const row = el('div', 'wc-strip-row'); const actions = el('div', 'wc-strip-actions');
    actions.append(button('更多城市', 'chevron_right', () => cardsContainer.scrollBy({left:260, behavior:reduced.matches ? 'instant' : 'smooth'})));
    actions.append(button('展开天气墙', 'expand_more', () => emit('toggle')), button('管理城市', 'add_location_alt', () => emit('manage')));
    row.append(cardsContainer, actions); root.append(row);
  }
  root.append(dialog);
  if (search) search.addEventListener('input', () => { const q = search.value.trim().toLocaleLowerCase(); cards.forEach(({card, name}) => {card.hidden = !name.toLocaleLowerCase().includes(q);}); }, {signal});
  const observer = new IntersectionObserver(entries => entries.forEach(entry => {const i = cards.findIndex(c => c.card === entry.target); if (i >= 0) motions[i].setVisible(entry.isIntersecting);}), {threshold:.1});
  cards.forEach(({card}) => observer.observe(card));
  document.addEventListener('visibilitychange', () => { if (document.hidden) stopAll(); }, {signal});
  reduced.addEventListener('change', stopAll, {signal});
  hoverCapable.addEventListener('change', stopAll, {signal});
  const entryKey = `weather-entry:${data.session_id}`;
  let entryConsumed = true;
  try {
    entryConsumed = sessionStorage.getItem(entryKey) === data.entry_id;
    if (data.cards.length && reduced.matches) sessionStorage.setItem(entryKey, data.entry_id);
  } catch (_) { /* A blocked storage policy safely leaves the component static. */ }
  if (!entryConsumed && !reduced.matches) {
    Promise.allSettled(Array.from(cardsContainer.querySelectorAll('img')).map(img => img.decode())).then(() => {
      if (!disposed) later(() => {
        // Streamlit can replace this render while imagery is decoding. Consume
        // the entry only when its surviving render is ready to start.
        try {
          if (sessionStorage.getItem(entryKey) === data.entry_id) return;
          if (data.cards.length) sessionStorage.setItem(entryKey, data.entry_id);
        } catch (_) { return; }
        motions.forEach(m => m.enter());
      }, 100);
    });
  }
  return () => { disposed = true; stopAll(); abort.abort(); observer.disconnect(); timers.forEach(clearTimeout); timers.clear(); if (dialog.open) dialog.close(); root.replaceChildren(); };
}
