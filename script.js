const chart = document.getElementById("chart");
const ctx = chart.getContext("2d");
const tooltip = document.getElementById("tooltip");
let payloadState = null;
let geometryState = null;

function percent(value) {
  return `${(value * 100).toFixed(1)}%`;
}

function formatDate(iso) {
  const date = new Date(`${iso}T00:00:00+09:00`);
  return new Intl.DateTimeFormat("ja-JP", {
    month: "short",
    day: "numeric",
  }).format(date);
}

function monthlyTicks(points) {
  const ticks = [];
  points.forEach((point, index) => {
    if (point.date.endsWith("-01")) {
      ticks.push({ index, label: point.date.slice(5, 7) });
    }
  });
  return ticks;
}

function drawChart(payload) {
  const dpr = window.devicePixelRatio || 1;
  const cssWidth = chart.clientWidth;
  const cssHeight = chart.clientHeight;

  chart.width = Math.floor(cssWidth * dpr);
  chart.height = Math.floor(cssHeight * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssWidth, cssHeight);

  const margin = { top: 28, right: 26, bottom: 48, left: 48 };
  const width = cssWidth - margin.left - margin.right;
  const height = cssHeight - margin.top - margin.bottom;
  const floorY = margin.top + height;
  const barWidth = width / payload.predictions.length;
  const maxValue = Math.max(Math.max(...payload.predictions.map((item) => item.probability)) * 1.14, 0.04);

  const bg = ctx.createLinearGradient(0, margin.top, 0, floorY);
  bg.addColorStop(0, "rgba(104, 209, 255, 0.06)");
  bg.addColorStop(1, "rgba(104, 209, 255, 0)");
  ctx.fillStyle = bg;
  ctx.fillRect(margin.left, margin.top, width, height);

  ctx.strokeStyle = "rgba(255,255,255,0.08)";
  ctx.lineWidth = 1;
  ctx.font = "12px Segoe UI";
  ctx.fillStyle = "rgba(200,219,234,0.8)";

  [0, 0.25, 0.5, 0.75, 1].forEach((ratio) => {
    const y = margin.top + height * ratio;
    ctx.beginPath();
    ctx.moveTo(margin.left, y);
    ctx.lineTo(margin.left + width, y);
    ctx.stroke();
    const label = `${Math.round((1 - ratio) * maxValue * 100)}%`;
    ctx.fillText(label, 8, y + 4);
  });

  const todayIndex = payload.predictions.findIndex((item) => item.date === payload.today);
  if (todayIndex >= 0) {
    const x = margin.left + barWidth * (todayIndex + 0.5);
    ctx.strokeStyle = "rgba(255, 209, 107, 0.8)";
    ctx.setLineDash([5, 7]);
    ctx.beginPath();
    ctx.moveTo(x, margin.top);
    ctx.lineTo(x, floorY);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  const gradient = ctx.createLinearGradient(0, margin.top, 0, floorY);
  gradient.addColorStop(0, "#76dbff");
  gradient.addColorStop(0.55, "#39bcff");
  gradient.addColorStop(1, "#0f6cff");

  payload.predictions.forEach((point, index) => {
    const valueHeight = (point.probability / maxValue) * height;
    const x = margin.left + index * barWidth;
    const y = floorY - valueHeight;
    ctx.fillStyle = gradient;
    ctx.fillRect(x + 0.35, y, Math.max(barWidth - 0.7, 1), valueHeight);
  });

  ctx.strokeStyle = "rgba(255,255,255,0.18)";
  ctx.beginPath();
  ctx.moveTo(margin.left, floorY);
  ctx.lineTo(margin.left + width, floorY);
  ctx.stroke();

  ctx.fillStyle = "rgba(200,219,234,0.8)";
  monthlyTicks(payload.predictions).forEach((tick) => {
    const x = margin.left + barWidth * (tick.index + 0.5);
    ctx.fillText(tick.label, x - 8, floorY + 22);
  });

  return { margin, width, height, floorY, barWidth, maxValue };
}

function populateTopDays(payload) {
  const host = document.getElementById("topDays");
  host.innerHTML = "";
  payload.topDays.forEach((item) => {
    const chip = document.createElement("article");
    chip.className = "day-chip";
    chip.innerHTML = `
      <span class="date">${formatDate(item.date)}</span>
      <strong>${percent(item.probability)}</strong>
      <span class="detail">${item.airTemp.toFixed(1)}C / ${item.seaTemp.toFixed(1)}C / moon ${item.moonAge.toFixed(1)}</span>
    `;
    host.appendChild(chip);
  });
}

function bindTooltip() {
  const scroller = document.getElementById("chartScroller");

  function show(clientX, clientY) {
    if (!payloadState || !geometryState) {
      return;
    }
    const rect = chart.getBoundingClientRect();
    const x = clientX - rect.left;
    const index = Math.max(
      0,
      Math.min(
        payloadState.predictions.length - 1,
        Math.floor((x - geometryState.margin.left) / geometryState.barWidth),
      ),
    );
    const point = payloadState.predictions[index];
    if (!point) {
      tooltip.hidden = true;
      return;
    }

    tooltip.hidden = false;
    tooltip.style.left = `${Math.min(
      scroller.scrollLeft + x + 16,
      scroller.scrollLeft + rect.width - 220,
    )}px`;
    tooltip.style.top = `${Math.max(16, clientY - rect.top - 96)}px`;
    tooltip.innerHTML = `
      <strong>${formatDate(point.date)}</strong>
      <span>${percent(point.probability)}</span>
      <span>${point.airTemp.toFixed(1)}C / ${point.seaTemp.toFixed(1)}C</span>
      <span>moon ${point.moonAge.toFixed(1)} / ${point.featureSource}</span>
    `;
  }

  chart.addEventListener("mousemove", (event) => show(event.clientX, event.clientY));
  chart.addEventListener(
    "touchmove",
    (event) => {
      const touch = event.touches[0];
      if (touch) {
        show(touch.clientX, touch.clientY);
      }
    },
    { passive: true },
  );
  chart.addEventListener("mouseleave", () => {
    tooltip.hidden = true;
  });
  chart.addEventListener("touchend", () => {
    tooltip.hidden = true;
  });
}

async function main() {
  const response = await fetch("./data/predictions.json");
  payloadState = await response.json();

  document.getElementById("title").textContent = `${payloadState.targetYear} X-Day Forecast`;
  document.getElementById("generatedAt").textContent = payloadState.generatedAt;
  document.getElementById("threshold").textContent = `X >= ${payloadState.xDayThreshold}匹`;
  document.getElementById("rangeLabel").textContent = `${payloadState.targetYear}-01-01 → ${payloadState.targetYear}-12-31`;
  document.getElementById("todayLabel").textContent = `today ${payloadState.today}`;

  populateTopDays(payloadState);
  geometryState = drawChart(payloadState);
}

bindTooltip();

window.addEventListener("resize", () => {
  if (payloadState) {
    geometryState = drawChart(payloadState);
  }
});

main().catch((error) => {
  console.error(error);
});
