let data = null;
let filtered = [];
let selectedIndex = 0;
let lastVideoSubtitleKey = "";

const $ = (id) => document.getElementById(id);

function msToTs(ms) {
  const total = Math.floor(ms / 1000);
  return `${Math.floor(total / 3600)}:${String(Math.floor((total % 3600) / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

function parseTs(value) {
  if (!value.trim()) return null;
  const parts = value.split(":").map((v) => Number.parseInt(v, 10));
  const final = parts.length === 2 ? [0, ...parts] : parts;
  return ((final[0] * 60 + final[1]) * 60 + final[2]) * 1000;
}

function idText(row) {
  return String(row.id);
}

function speakerText(row) {
  const mode = $("speakerMode").value;
  if (mode === "name" && row.speaker !== "SFX") return `(${row.speaker}) ${row.translation_raw || ""}`;
  return row.translation_raw || "";
}

function splitJaClauses(text, maxChars = 34) {
  const clean = stripRichText(text || "").replace(/\s+/g, " ").trim();
  if (!clean) return [];
  if (["うん。", "そうだね。", "OK。", "よし。", "（笑）"].includes(clean)) return [clean];
  const { text: protectedText, restore } = protectSubtitleText(clean);
  const raw = splitAtReadableEdges(protectedText);
  const pieces = raw.flatMap((chunk) => splitLongReadableChunk(chunk, maxChars));
  return mergeBadSubtitleEdges(pieces.map((piece) => restore(piece).trim().replace(/^、+/, "")).filter(Boolean));
}

function protectSubtitleText(text) {
  const phrases = ["Time to Explain", "ブロスタパスPlus", "ブロスタパス", "ストレンジャー・シングス", "スター・パーク", "Supercell Make", "Brawl Talk", "Brawlies", "ゲームプレイ", "ジュエルチップ"];
  const map = [];
  const store = (value) => {
    const key = `__KEEP_${map.length}__`;
    map.push([key, value]);
    return key;
  };
  let output = text;
  phrases.forEach((phrase) => {
    output = output.replaceAll(phrase, store(phrase));
  });
  output = output.replace(/「[^」]*」|『[^』]*』|“[^”]*”|"[^"]*"/g, (match) => store(match));
  return {
    text: output,
    restore(value) {
      return map.reduce((acc, [key, original]) => acc.replaceAll(key, original), value);
    },
  };
}

function splitAtReadableEdges(text) {
  const connectors = ["だから、", "ただ、", "でも、", "それで、", "じゃあ、", "そして、", "つまり、", "たとえば、", "ちなみに、", "一方で、"];
  const output = [];
  let current = "";
  let i = 0;
  while (i < text.length) {
    const connector = connectors.find((word) => text.startsWith(word, i));
    if (connector && current) {
      output.push(current);
      current = connector;
      i += connector.length;
      continue;
    }
    current += text[i];
    if ("。！？!?".includes(text[i]) || (text[i] === "、" && current.length >= 10)) {
      output.push(current);
      current = "";
    }
    i += 1;
  }
  if (current) output.push(current);
  return output;
}

function splitLongReadableChunk(chunk, maxChars) {
  if (chunk.length <= maxChars) return [chunk];
  const preferred = ["、", "ということ", "という話", "という感じ", "だから", "なので", "だけど", "けど", "でも", "なら", "時に", "場合", "理由", "ために", "ように", "から", "まで", "には", "では", "とは", "ても"];
  const output = [];
  let rest = chunk;
  while (rest.length > maxChars) {
    const window = rest.slice(0, maxChars + 1);
    const cuts = [];
    preferred.forEach((word) => {
      let pos = window.indexOf(word);
      while (pos >= 0) {
        const cut = pos + word.length;
        if (cut >= 10 && !badSubtitleBoundary(rest.slice(0, cut), rest.slice(cut))) cuts.push(cut);
        pos = window.indexOf(word, pos + 1);
      }
    });
    let cut = cuts.length ? cuts.sort((a, b) => Math.abs(a - 22) - Math.abs(b - 22))[0] : 0;
    if (!cut) {
      for (let i = Math.min(rest.length - 1, maxChars); i >= 10; i -= 1) {
        if (!badSubtitleBoundary(rest.slice(0, i), rest.slice(i)) && !/[ぁ-んァ-ンーA-Za-z0-9]/.test(rest[i - 1] + rest[i])) {
          cut = i;
          break;
        }
      }
    }
    cut ||= Math.min(rest.length, maxChars);
    output.push(rest.slice(0, cut).trim());
    rest = rest.slice(cut).replace(/^[、\s]+/, "");
  }
  if (rest) output.push(rest);
  return output;
}

function badSubtitleBoundary(left, right) {
  const badEndings = ["の", "に", "を", "が", "は", "で", "と", "も", "や", "こと", "もの", "ため", "場合", "時", "理由", "可能性", "重要なこと", "側と", "要素を", "報酬を", "質問を"];
  const l = left.replace(/[、\s]+$/g, "");
  const r = right.replace(/^[、\s]+/g, "");
  return badEndings.some((ending) => l.endsWith(ending)) || /^[」』）)、。]/.test(r) || (l.match(/「/g)?.length || 0) > (l.match(/」/g)?.length || 0);
}

function mergeBadSubtitleEdges(pieces) {
  const output = [];
  pieces.forEach((piece) => {
    if (!output.length) {
      output.push(piece);
      return;
    }
    const merged = `${output[output.length - 1]}${piece}`;
    if ((badSubtitleBoundary(output[output.length - 1], piece) || piece.length <= 6 || output[output.length - 1].length <= 4) && merged.length <= 46) {
      output[output.length - 1] = merged;
    } else {
      output.push(piece);
    }
  });
  return output;
}

function splitEnClauses(text) {
  return String(text || "")
    .replace(/\s+/g, " ")
    .trim()
    .split(/(?<=[.!?])\s+|,\s+(?=(?:and|but|so|because|when|if|then|like|you|we|I)\b)/i)
    .map((part) => part.trim())
    .filter(Boolean);
}

function buildShortsUnits(row) {
  const clauses = row.ja_clauses || splitJaClauses(row.translation_raw || "");
  if (!clauses.length) return [];
  const start = Number(row.start_ms || 0);
  const end = Math.max(start + 900, Number(row.end_ms || start + 900));
  const duration = end - start;
  const weights = clauses.map((clause) => Math.max(4, stripRichText(clause).length));
  const total = weights.reduce((sum, value) => sum + value, 0) || clauses.length;
  let cursor = start;
  return clauses.map((clause, index) => {
    const elapsedWeight = weights.slice(0, index + 1).reduce((sum, value) => sum + value, 0);
    const rawEnd = index === clauses.length - 1 ? end : start + Math.round((duration * elapsedWeight) / total);
    const unit = { text: clause, start_ms: cursor, end_ms: Math.max(cursor + 550, Math.min(rawEnd, end)) };
    cursor = unit.end_ms;
    return unit;
  });
}

function alignEnglishToJa(enClauses, jaClauses) {
  if (!jaClauses.length) return [];
  const clean = enClauses.filter(Boolean);
  if (!clean.length) return jaClauses.map(() => "");
  if (clean.length === jaClauses.length) return clean;
  const words = clean.join(" ").split(/\s+/).filter(Boolean);
  if (jaClauses.length === 1) return [words.join(" ")];
  const weights = jaClauses.map((clause) => Math.max(4, stripRichText(clause).length));
  const total = weights.reduce((sum, value) => sum + value, 0) || 1;
  const output = [];
  let cursor = 0;
  weights.forEach((_, index) => {
    if (index === weights.length - 1) {
      output.push(words.slice(cursor).join(" "));
      return;
    }
    let target = Math.round((words.length * weights.slice(0, index + 1).reduce((sum, value) => sum + value, 0)) / total);
    target = Math.max(cursor + 1, Math.min(target, words.length - (weights.length - index - 1)));
    output.push(words.slice(cursor, target).join(" "));
    cursor = target;
  });
  return output;
}

function refreshClauseData(row) {
  row.ja_clauses = splitJaClauses(row.translation_raw || "");
  row.en_clauses = splitEnClauses(row.original || "");
  const alignedEn = alignEnglishToJa(row.en_clauses, row.ja_clauses);
  row.shorts_segments = buildShortsUnits(row).map((unit, index) => ({
    ...unit,
    en: alignedEn[index] || "",
  }));
  row.shorts_units = row.shorts_segments;
}

function shortsClauseEnabled() {
  return $("shortsClauseMode").checked;
}

function overlaySettings() {
  return {
    x: Number($("overlayX")?.value || 50),
    bottom: Number($("overlayBottom")?.value || 7),
    width: Number($("overlayWidth")?.value || $("textWidth")?.value || 92),
    gap: Number($("overlayGap")?.value || 10),
    jaScale: Number($("videoJaScale")?.value || 100),
    enScale: Number($("videoEnScale")?.value || 72),
  };
}

function chunkAt(row, ms, lang = "ja") {
  if (!shortsClauseEnabled()) return lang === "ja" ? speakerText(row) : row.original || "";
  const units = row.shorts_segments || row.shorts_units || [];
  if (!units.length) return lang === "ja" ? speakerText(row) : row.original || "";
  let index = units.findIndex((unit) => unit.start_ms <= ms && unit.end_ms > ms);
  if (index < 0) index = 0;
  const unit = units[index];
  if (lang === "en") {
    return unit.en || "";
  }
  const text = unit.text || row.translation_raw || "";
  if ($("speakerMode").value === "name" && row.speaker !== "SFX") return `(${row.speaker}) ${text}`;
  return text;
}

function activeRowsAt(ms) {
  if (!data) return [];
  if (shortsClauseEnabled()) {
    const shortsDirect = data.segments.filter((item) =>
      (item.shorts_segments || item.shorts_units || []).some((segment) => segment.start_ms <= ms && segment.end_ms > ms)
    );
    if (shortsDirect.length) return suppressTinyOverlaps(shortsDirect, ms);
  }
  const direct = data.segments.filter((item) => item.start_ms <= ms && item.end_ms > ms);
  if (direct.length) return suppressTinyOverlaps(direct, ms);
  return data.segments.filter((item) => item.end_ms < ms && ms - item.end_ms <= 900).slice(-4);
}

function suppressTinyOverlaps(rows, ms) {
  if (rows.length <= 1) return rows;
  const sorted = [...rows].sort((a, b) => a.start_ms - b.start_ms || a.end_ms - b.end_ms);
  return sorted.filter((row) => {
    return !sorted.some((other) => {
      const overlap = row.end_ms - other.start_ms;
      return other.start_ms > row.start_ms && ms >= other.start_ms && overlap > 0 && overlap <= 500;
    });
  });
}

async function loadData() {
  data = await fetch("/api/data").then((res) => res.json());
  fillFilters();
  applyFilters();
  selectRow(0);
  $("exportEnd").value = msToTs(data.meta.duration_ms);
}

function fillFilters() {
  $("topicFilter").innerHTML = `<option value="">All topics</option>` + data.topics.map((t) => `<option>${escapeHtml(t.topic)}</option>`).join("");
  const speakers = [...new Set(data.segments.map((s) => s.speaker))].sort();
  $("speakerFilter").innerHTML = `<option value="">All speakers</option>` + speakers.map((s) => `<option>${escapeHtml(s)}</option>`).join("");
}

function applyFilters() {
  const q = $("searchInput").value.trim().toLowerCase();
  const topic = $("topicFilter").value;
  const speaker = $("speakerFilter").value;
  const reviewOnly = $("reviewOnly").checked;
  const qualityOnly = $("qualityOnly").checked;
  const start = parseTs($("startFilter").value);
  const end = parseTs($("endFilter").value);
  filtered = data.segments.filter((row) => {
    if (topic && row.topic !== topic) return false;
    if (speaker && row.speaker !== speaker) return false;
    if (reviewOnly && !row.speaker_review) return false;
    if (qualityOnly && !(row.quality_flags || []).length) return false;
    if (start !== null && row.end_ms < start) return false;
    if (end !== null && row.start_ms > end) return false;
    const haystack = `${row.original} ${row.translation_raw} ${row.topic} ${row.speaker}`.toLowerCase();
    return !q || haystack.includes(q);
  });
  renderTable();
}

function renderTable() {
  $("rowCount").textContent = `${filtered.length} / ${data.segments.length} rows`;
  $("subtitleRows").innerHTML = filtered
    .map((row, i) => {
      const selected = data.segments[selectedIndex]?.id === row.id ? "selected" : "";
      return `<tr class="${selected}" data-i="${i}">
        <td>${row.start} - ${row.end}</td>
        <td>${escapeHtml(row.speaker)}</td>
        <td>${row.speaker_review ? `<span class="review-badge">${escapeHtml(row.speaker_source || "review")}</span>` : `<span class="review-badge ok">ok</span>`}</td>
        <td>${(row.quality_flags || []).length ? `<span class="review-badge">${escapeHtml(row.quality_flags.join(", "))}</span>` : `<span class="review-badge ok">ok</span>`}</td>
        <td>${escapeHtml(row.topic)}</td>
        <td>${escapeHtml(stripRichText(row.translation_raw || ""))}</td>
        <td>${escapeHtml(row.original || "")}</td>
      </tr>`;
    })
    .join("");
}

function selectRow(indexInFiltered) {
  if (!filtered.length) return;
  const row = filtered[Math.max(0, Math.min(filtered.length - 1, indexInFiltered))];
  selectedIndex = data.segments.findIndex((item) => item.id === row.id);
  renderDetails(row);
  renderEditor(row);
  renderTable();
}

function renderDetails(row) {
  $("detailTime").textContent = `${row.start} - ${row.end}`;
  $("detailTopic").textContent = `${row.speaker} / ${row.topic}`;
  $("detailJa").innerHTML = richTextToHtml(row.translation_raw || "");
  $("detailEn").textContent = row.original || "";
}

function renderEditor(row) {
  refreshClauseData(row);
  $("selectedMeta").textContent = `${row.start} - ${row.end} / ${row.speaker} / ${row.topic}`;
  $("speakerEdit").value = row.speaker || "Team";
  $("startEdit").value = row.start || msToTs(row.start_ms);
  $("endEdit").value = row.end || msToTs(row.end_ms);
  $("topicEdit").value = row.topic || "";
  $("jpEdit").value = row.translation_raw || "";
  $("enEdit").value = row.original || "";
  renderClausePanel(row);
  renderPreview();
}

function renderClausePanel(row) {
  const segments = row.shorts_segments || row.shorts_units || [];
  $("clauseSummary").textContent = `${segments.length}分割`;
  $("clauseList").innerHTML = segments
    .map((segment, index) => {
      const unit = segment;
      const time = unit ? `${msToTs(unit.start_ms)} - ${msToTs(unit.end_ms)}` : "";
      return `<div class="clause-item"><span>${index + 1}</span><p>${escapeHtml(segment.text || "")}</p><small>${time}</small></div>`;
    })
    .join("");
}

function refreshClausePanelFromInputs() {
  const row = data?.segments[selectedIndex];
  if (!row) return;
  const draft = {
    ...row,
    translation_raw: $("jpEdit").value,
    original: $("enEdit").value,
    start_ms: parseTs($("startEdit").value) ?? row.start_ms,
    end_ms: parseTs($("endEdit").value) ?? row.end_ms,
  };
  refreshClauseData(draft);
  renderClausePanel(draft);
  const previewRow = data.segments[selectedIndex];
  const oldClauses = previewRow.ja_clauses;
  const oldUnits = previewRow.shorts_units;
  const oldSegments = previewRow.shorts_segments;
  const oldEnClauses = previewRow.en_clauses;
  const oldJa = previewRow.translation_raw;
  const oldEn = previewRow.original;
  previewRow.ja_clauses = draft.ja_clauses;
  previewRow.shorts_units = draft.shorts_units;
  previewRow.shorts_segments = draft.shorts_segments;
  previewRow.en_clauses = draft.en_clauses;
  previewRow.translation_raw = draft.translation_raw;
  previewRow.original = draft.original;
  renderPreview();
  previewRow.ja_clauses = oldClauses;
  previewRow.shorts_units = oldUnits;
  previewRow.shorts_segments = oldSegments;
  previewRow.en_clauses = oldEnClauses;
  previewRow.translation_raw = oldJa;
  previewRow.original = oldEn;
}

function renderPreview() {
  const row = data.segments[selectedIndex];
  if (!row) return;
  const preview = $("assetPreview");
  const videoShell = document.querySelector(".video-shell");
  const format = $("formatSelect").value;
  preview.classList.toggle("short", format === "short");
  preview.classList.toggle("long", format === "long");
  preview.classList.toggle("pop-animation", $("popAnimation").checked);
  preview.style.background = $("bgColor").value;
  preview.style.setProperty("--subtitle-width", `${$("textWidth").value}%`);
  preview.style.setProperty("--jp-size", `${$("fontSize").value}px`);
  preview.style.setProperty("--en-size", `${Math.max(18, Number($("fontSize").value) - 14)}px`);
  preview.style.setProperty("--jp-color", $("jpColor").value);
  preview.style.setProperty("--en-color", $("enColor").value);
  preview.style.setProperty("--outline-size", `${$("outlineSize").value}px`);
  preview.style.setProperty("--outline-color", $("outlineColor").value);
  preview.style.setProperty("--shadow-x", `${$("shadowX").value}px`);
  preview.style.setProperty("--shadow-y", `${$("shadowY").value}px`);
  preview.style.setProperty("--shadow-x-en", `${Number($("shadowX").value) * 0.8}px`);
  preview.style.setProperty("--shadow-y-en", `${Number($("shadowY").value) * 0.85}px`);
  preview.style.setProperty("--shadow-color", hexToRgba($("shadowColor").value, Number($("shadowOpacity").value) / 100));
  if (videoShell) {
    const overlay = overlaySettings();
    [
      "--jp-size",
      "--en-size",
      "--jp-color",
      "--en-color",
      "--outline-size",
      "--outline-color",
      "--shadow-x",
      "--shadow-y",
      "--shadow-x-en",
      "--shadow-y-en",
      "--shadow-color",
    ].forEach((name) => videoShell.style.setProperty(name, preview.style.getPropertyValue(name)));
    videoShell.style.setProperty("--overlay-x", `${overlay.x}%`);
    videoShell.style.setProperty("--overlay-bottom", `${overlay.bottom}%`);
    videoShell.style.setProperty("--video-subtitle-width", `${overlay.width}%`);
    videoShell.style.setProperty("--overlay-gap", `${overlay.gap}px`);
    videoShell.style.setProperty("--video-jp-size", `${Math.max(12, Number($("fontSize").value) * overlay.jaScale / 100)}px`);
    videoShell.style.setProperty("--video-en-size", `${Math.max(12, Number($("fontSize").value) * overlay.enScale / 100)}px`);
    videoShell.classList.toggle("pop-animation", $("popAnimation").checked);
  }
  const ms = row.start_ms;
  const jpText = chunkAt(row, ms, "ja");
  const enText = chunkAt(row, ms, "en");
  $("previewJa").innerHTML = richTextToHtml(jpText);
  $("previewEn").innerHTML = richTextToHtml(enText);
  $("fontSizeValue").textContent = $("fontSize").value;
  $("textWidthValue").textContent = `${$("textWidth").value}%`;
  $("outlineSizeValue").textContent = `${$("outlineSize").value}px`;
  $("shadowXValue").textContent = `${$("shadowX").value}px`;
  $("shadowYValue").textContent = `${$("shadowY").value}px`;
  $("shadowOpacityValue").textContent = `${$("shadowOpacity").value}%`;
  if ($("overlayXValue")) {
    const overlay = overlaySettings();
    $("overlayXValue").textContent = `${overlay.x}%`;
    $("overlayBottomValue").textContent = `${overlay.bottom}%`;
    $("overlayWidthValue").textContent = `${overlay.width}%`;
    $("overlayGapValue").textContent = `${overlay.gap}px`;
    $("videoJaScaleValue").textContent = `${overlay.jaScale}%`;
    $("videoEnScaleValue").textContent = `${overlay.enScale}%`;
  }
  renderVideoSubtitles();
}

function applyEdit() {
  const row = data.segments[selectedIndex];
  if (!row) return;
  row.speaker = $("speakerEdit").value.trim() || "Group";
  row.start = $("startEdit").value.trim() || row.start;
  row.end = $("endEdit").value.trim() || row.end;
  row.start_ms = parseTs(row.start) ?? row.start_ms;
  row.end_ms = parseTs(row.end) ?? row.end_ms;
  row.topic = $("topicEdit").value.trim() || row.topic;
  row.translation_raw = $("jpEdit").value.trim();
  row.subtitle_ja = row.translation_raw;
  row.original = $("enEdit").value.trim();
  row.subtitle_en = row.original;
  refreshClauseData(row);
  row.translation = row.speaker === "SFX" ? row.translation_raw : `(${row.speaker}) ${row.translation_raw}`;
  row.speaker_review = false;
  row.speaker_source = "edited";
  $("selectedMeta").textContent = `${row.start} - ${row.end} / ${row.speaker} / ${row.topic}`;
  renderDetails(row);
  renderClausePanel(row);
  renderPreview();
  renderTable();
}

function newIdAfter(row) {
  const base = idText(row || { id: "new" });
  let suffix = 1;
  let id = `${base}.${suffix}`;
  const ids = new Set(data.segments.map((item) => idText(item)));
  while (ids.has(id)) {
    suffix += 1;
    id = `${base}.${suffix}`;
  }
  return id;
}

function blankRowAfter(row) {
  const start = row ? row.end_ms : 0;
  const end = start + 1200;
  return {
    id: newIdAfter(row),
    start_ms: start,
    end_ms: end,
    start: msToTs(start),
    end: msToTs(end),
    speaker: row?.speaker || "Dani",
    topic: row?.topic || "手動追加",
    original: "",
    translation_raw: "",
    translation: "",
    subtitle_ja: "",
    subtitle_en: "",
    translation_status: "manual_editor",
    speaker_source: "edited",
    speaker_review: false,
  };
}

function sortSegments() {
  data.segments.sort((a, b) => a.start_ms - b.start_ms || a.end_ms - b.end_ms || idText(a).localeCompare(idText(b)));
}

function refreshAfterMutation(rowId) {
  sortSegments();
  fillFilters();
  applyFilters();
  const index = data.segments.findIndex((row) => idText(row) === idText({ id: rowId }));
  selectedIndex = Math.max(0, index);
  const filteredIndex = filtered.findIndex((row) => idText(row) === idText({ id: rowId }));
  selectRow(filteredIndex >= 0 ? filteredIndex : 0);
}

function setSelectedSpeaker() {
  const row = data.segments[selectedIndex];
  if (!row) return;
  row.speaker = $("bulkSpeaker").value;
  row.speaker_source = "edited";
  row.speaker_review = false;
  row.translation = row.speaker === "SFX" ? row.translation_raw : `(${row.speaker}) ${row.translation_raw}`;
  renderEditor(row);
  renderDetails(row);
  renderTable();
}

function setFilteredSpeakers() {
  const speaker = $("bulkSpeaker").value;
  const ids = new Set(filtered.map((row) => idText(row)));
  data.segments.forEach((row) => {
    if (!ids.has(idText(row))) return;
    row.speaker = speaker;
    row.speaker_source = "edited_bulk";
    row.speaker_review = false;
    row.translation = row.speaker === "SFX" ? row.translation_raw : `(${row.speaker}) ${row.translation_raw}`;
  });
  applyFilters();
}

function insertAfterSelected() {
  const row = data.segments[selectedIndex];
  const next = blankRowAfter(row);
  data.segments.splice(selectedIndex + 1, 0, next);
  refreshAfterMutation(next.id);
}

function duplicateSelected() {
  const row = data.segments[selectedIndex];
  if (!row) return;
  const copy = { ...row, id: newIdAfter(row), translation_status: "manual_duplicate", speaker_source: "edited", speaker_review: false };
  data.segments.splice(selectedIndex + 1, 0, copy);
  refreshAfterMutation(copy.id);
}

function deleteSelected() {
  if (!data.segments.length) return;
  const row = data.segments[selectedIndex];
  if (!confirm(`字幕 ${row.id} を削除しますか？`)) return;
  data.segments.splice(selectedIndex, 1);
  refreshAfterMutation(data.segments[Math.max(0, selectedIndex - 1)]?.id || data.segments[0]?.id);
}

function splitText(text) {
  const clean = String(text || "");
  const marks = ["。", "？", "！", ".", "?", "!"];
  for (const mark of marks) {
    const pos = clean.indexOf(mark);
    if (pos > 0 && pos < clean.length - 1) return [clean.slice(0, pos + 1).trim(), clean.slice(pos + 1).trim()];
  }
  const mid = Math.floor(clean.length / 2);
  return [clean.slice(0, mid).trim(), clean.slice(mid).trim()];
}

function splitSelected() {
  const row = data.segments[selectedIndex];
  if (!row) return;
  const mid = Math.floor((row.start_ms + row.end_ms) / 2);
  const [ja1, ja2] = splitText(row.translation_raw);
  const [en1, en2] = splitText(row.original);
  const next = { ...row, id: newIdAfter(row), start_ms: mid, start: msToTs(mid), original: en2, translation_raw: ja2, subtitle_en: en2, subtitle_ja: ja2, translation_status: "manual_split" };
  row.end_ms = mid;
  row.end = msToTs(mid);
  row.original = en1;
  row.translation_raw = ja1;
  row.subtitle_en = en1;
  row.subtitle_ja = ja1;
  row.translation_status = "manual_split";
  data.segments.splice(selectedIndex + 1, 0, next);
  [row, next].forEach((item) => {
    item.translation = item.speaker === "SFX" ? item.translation_raw : `(${item.speaker}) ${item.translation_raw}`;
    item.speaker_source = "edited";
    item.speaker_review = false;
  });
  refreshAfterMutation(next.id);
}

function mergeNextSelected() {
  const row = data.segments[selectedIndex];
  const next = data.segments[selectedIndex + 1];
  if (!row || !next) return;
  row.end_ms = Math.max(row.end_ms, next.end_ms);
  row.end = msToTs(row.end_ms);
  row.original = [row.original, next.original].filter(Boolean).join(" ");
  row.translation_raw = [row.translation_raw, next.translation_raw].filter(Boolean).join("\n");
  row.subtitle_en = row.original;
  row.subtitle_ja = row.translation_raw;
  row.translation = row.speaker === "SFX" ? row.translation_raw : `(${row.speaker}) ${row.translation_raw}`;
  row.translation_status = "manual_merge";
  row.speaker_source = "edited";
  row.speaker_review = false;
  data.segments.splice(selectedIndex + 1, 1);
  refreshAfterMutation(row.id);
}

function markReviewed() {
  const row = data.segments[selectedIndex];
  if (!row) return;
  row.speaker_review = false;
  row.speaker_source = row.speaker_source || "reviewed";
  renderTable();
  renderDetails(row);
}

async function saveData() {
  applyEdit();
  await fetch("/api/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  alert("JSON/CSVに保存しました。");
}

async function exportMp4() {
  applyEdit();
  $("exportStatus").textContent = "書き出し中...";
  const settings = {
    format: $("formatSelect").value,
    speakerMode: $("speakerMode").value,
    fontSize: Number($("fontSize").value),
    textWidth: Number($("textWidth").value),
    jpColor: $("jpColor").value,
    enColor: $("enColor").value,
    bgColor: $("bgColor").value,
    outlineColor: $("outlineColor").value,
    outlineSize: Number($("outlineSize").value),
    shadowColor: $("shadowColor").value,
    shadowX: Number($("shadowX").value),
    shadowY: Number($("shadowY").value),
    shadowOpacity: Number($("shadowOpacity").value),
    shortsClauseMode: $("shortsClauseMode").checked,
    popAnimation: $("popAnimation").checked,
    overlayX: Number($("overlayX")?.value || 50),
    overlayBottom: Number($("overlayBottom")?.value || 7),
    overlayWidth: Number($("overlayWidth")?.value || $("textWidth").value),
    overlayGap: Number($("overlayGap")?.value || 10),
    videoJaScale: Number($("videoJaScale")?.value || 100),
    videoEnScale: Number($("videoEnScale")?.value || 72),
    start: $("exportStart").value,
    end: $("exportEnd").value,
  };
  const res = await fetch("/api/export", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ data, settings }),
  });
  const payload = await res.json();
  if (!payload.ok) {
    $("exportStatus").textContent = payload.error || "書き出しに失敗しました。";
    return;
  }
  $("exportStatus").innerHTML = `
    <a href="${payload.jp_url || payload.url}">日本語MP4をダウンロード</a>
    ${payload.en_url ? `<a href="${payload.en_url}">英語MP4をダウンロード</a>` : ""}
  `;
}

function jumpVideo() {
  const row = data.segments[selectedIndex];
  const video = $("video");
  video.currentTime = row.start_ms / 1000;
  renderVideoSubtitles();
  video.play();
}

function renderVideoSubtitles() {
  if (!data) return;
  const ms = $("video").currentTime * 1000;
  let rows = activeRowsAt(ms);
  if (!rows.length && data.segments[selectedIndex]) rows = [data.segments[selectedIndex]];
  const limited = rows.slice(-1);
  const jaTexts = limited.map((row) => chunkAt(row, ms, "ja"));
  const enTexts = limited.map((row) => chunkAt(row, ms, "en"));
  $("videoSubtitleJa").innerHTML = jaTexts.map(richTextToHtml).join("\n");
  $("videoSubtitleEn").innerHTML = enTexts.map(richTextToHtml).join("\n");
  const overlay = $("videoSubtitleOverlay");
  const key = `${jaTexts.join("|")}__${enTexts.join("|")}`;
  if ($("popAnimation").checked && key !== lastVideoSubtitleKey) {
    overlay.classList.remove("animate-pop");
    void overlay.offsetWidth;
    overlay.classList.add("animate-pop");
  } else if (!$("popAnimation").checked) {
    overlay.classList.remove("animate-pop");
  }
  lastVideoSubtitleKey = key;
}

function move(delta) {
  const next = Math.max(0, Math.min(data.segments.length - 1, selectedIndex + delta));
  const row = data.segments[next];
  const filteredIndex = filtered.findIndex((item) => item.id === row.id);
  selectedIndex = next;
  renderDetails(row);
  renderEditor(row);
  renderTable();
  if (filteredIndex >= 0) {
    const trs = [...document.querySelectorAll("#subtitleRows tr")];
    trs[filteredIndex]?.scrollIntoView({ block: "center" });
  }
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" })[char]);
}

function stripRichText(value) {
  return String(value).replace(/\[color=#[0-9a-fA-F]{6}\]([\s\S]*?)\[\/color\]/g, "$1");
}

function richTextToHtml(value) {
  const text = String(value || "");
  let output = "";
  let i = 0;
  const pattern = /\[color=(#[0-9a-fA-F]{6})\]([\s\S]*?)\[\/color\]/g;
  let match;
  while ((match = pattern.exec(text))) {
    output += escapeHtml(text.slice(i, match.index));
    output += `<span style="color:${match[1]}">${escapeHtml(match[2])}</span>`;
    i = pattern.lastIndex;
  }
  output += escapeHtml(text.slice(i));
  return output;
}

function applyInlineColor() {
  const textarea = $("jpEdit");
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  if (start === end) return;
  const color = $("inlineColor").value;
  const value = textarea.value;
  textarea.value = `${value.slice(0, start)}[color=${color}]${value.slice(start, end)}[/color]${value.slice(end)}`;
  textarea.focus();
  textarea.selectionStart = start;
  textarea.selectionEnd = end + 23;
  applyEdit();
}

function clearInlineColor() {
  $("jpEdit").value = stripRichText($("jpEdit").value);
  applyEdit();
}

function hexToRgba(hex, alpha) {
  const value = hex.replace("#", "");
  const r = Number.parseInt(value.slice(0, 2), 16);
  const g = Number.parseInt(value.slice(2, 4), 16);
  const b = Number.parseInt(value.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function applyBrawlStylePreset() {
  $("jpColor").value = "#ffffff";
  $("enColor").value = "#ffffff";
  $("outlineColor").value = "#050505";
  $("outlineSize").value = 4;
  $("shadowColor").value = "#000000";
  $("shadowX").value = 2;
  $("shadowY").value = 4;
  $("shadowOpacity").value = 100;
  $("fontSize").value = 40;
  renderPreview();
}

document.addEventListener("click", (event) => {
  const tab = event.target.closest(".tab");
  if (tab) {
    document.querySelectorAll(".tab").forEach((button) => button.classList.remove("active"));
    document.querySelectorAll(".page").forEach((page) => page.classList.remove("active"));
    tab.classList.add("active");
    $(tab.dataset.page).classList.add("active");
  }
  const tr = event.target.closest("#subtitleRows tr");
  if (tr) selectRow(Number(tr.dataset.i));
});

["searchInput", "topicFilter", "speakerFilter", "startFilter", "endFilter", "reviewOnly", "qualityOnly"].forEach((id) => $(id).addEventListener("input", applyFilters));
$("clearFilters").addEventListener("click", () => {
  ["searchInput", "startFilter", "endFilter"].forEach((id) => ($(id).value = ""));
  $("topicFilter").value = "";
  $("speakerFilter").value = "";
  applyFilters();
});
$("editSelectedFromList").addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach((button) => button.classList.remove("active"));
  document.querySelectorAll(".page").forEach((page) => page.classList.remove("active"));
  document.querySelector('.tab[data-page="editorPage"]').classList.add("active");
  $("editorPage").classList.add("active");
  renderEditor(data.segments[selectedIndex]);
});
[
  "formatSelect",
  "speakerMode",
  "fontSize",
  "textWidth",
  "jpColor",
  "enColor",
  "bgColor",
  "outlineColor",
  "outlineSize",
  "shadowColor",
  "shadowX",
  "shadowY",
  "shadowOpacity",
  "shortsClauseMode",
  "popAnimation",
  "overlayX",
  "overlayBottom",
  "overlayWidth",
  "overlayGap",
  "videoJaScale",
  "videoEnScale",
].forEach((id) => $(id).addEventListener("input", renderPreview));
["jpEdit", "enEdit", "startEdit", "endEdit"].forEach((id) => $(id).addEventListener("input", refreshClausePanelFromInputs));
$("brawlStylePreset").addEventListener("click", applyBrawlStylePreset);
$("applyEdit").addEventListener("click", applyEdit);
$("applyInlineColor").addEventListener("click", applyInlineColor);
$("clearInlineColor").addEventListener("click", clearInlineColor);
$("setSelectedSpeaker").addEventListener("click", setSelectedSpeaker);
$("setFilteredSpeaker").addEventListener("click", setFilteredSpeakers);
$("insertAfterRow").addEventListener("click", insertAfterSelected);
$("duplicateRow").addEventListener("click", duplicateSelected);
$("deleteRow").addEventListener("click", deleteSelected);
$("splitRow").addEventListener("click", splitSelected);
$("mergeNextRow").addEventListener("click", mergeNextSelected);
$("markReviewed").addEventListener("click", markReviewed);
$("saveData").addEventListener("click", saveData);
$("exportBtn").addEventListener("click", exportMp4);
$("jumpBtn").addEventListener("click", jumpVideo);
$("prevBtn").addEventListener("click", () => move(-1));
$("nextBtn").addEventListener("click", () => move(1));
$("youtubeBtn").addEventListener("click", () => $("youtubeWrap").classList.toggle("hidden"));
$("video").addEventListener("timeupdate", () => {
  const ms = $("video").currentTime * 1000;
  renderVideoSubtitles();
  const row = activeRowsAt(ms)[0];
  if (row && data.segments[selectedIndex]?.id !== row.id) {
    selectedIndex = data.segments.findIndex((item) => item.id === row.id);
    renderDetails(row);
    renderEditor(row);
    renderTable();
  }
});

loadData();
