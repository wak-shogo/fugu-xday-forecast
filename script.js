const probabilityChart = document.getElementById("probChart");
const minChart = document.getElementById("minChart");
const maxChart = document.getElementById("maxChart");

const simulatorNodes = {
  airTemp: {
    input: document.getElementById("airSlider"),
    value: document.getElementById("airValue"),
    unit: "C",
  },
  seaTemp: {
    input: document.getElementById("seaSlider"),
    value: document.getElementById("seaValue"),
    unit: "C",
  },
  moonAge: {
    input: document.getElementById("moonSlider"),
    value: document.getElementById("moonValue"),
    unit: "d",
  },
};

const outputNodes = {
  probability: document.getElementById("simProbability"),
  min: document.getElementById("simMin"),
  max: document.getElementById("simMax"),
};

const chartState = new Map();
let payloadState = null;
let simulatorInitialized = false;

function clamp(value, lower, upper) {
  return Math.max(lower, Math.min(upper, value));
}

function percent(value) {
  return `${(value * 100).toFixed(1)}%`;
}

function countText(value) {
  return `${value.toFixed(1)}匹`;
}

function formatControlValue(key, value) {
  if (key === "moonAge") {
    return `${value.toFixed(1)}日`;
  }
  return `${value.toFixed(1)}℃`;
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
      const month = Number(point.date.slice(5, 7));
      ticks.push({ index, label: `${month}月` });
    }
  });
  return ticks;
}

function featureSourceLabel(source) {
  const labels = {
    archive: "実測気象",
    forecast: "予報気象",
    climatology: "平年気候",
  };
  return labels[source] || source;
}

function prepareCanvas(canvas) {
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const cssWidth = canvas.clientWidth;
  const cssHeight = canvas.clientHeight;

  canvas.width = Math.floor(cssWidth * dpr);
  canvas.height = Math.floor(cssHeight * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssWidth, cssHeight);
  return { ctx, cssWidth, cssHeight };
}

function drawGrid(ctx, geometry, maxValue, formatter) {
  const { margin, width, height, floorY } = geometry;
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
    ctx.fillText(formatter((1 - ratio) * maxValue), 8, y + 4);
  });

  ctx.strokeStyle = "rgba(255,255,255,0.18)";
  ctx.beginPath();
  ctx.moveTo(margin.left, floorY);
  ctx.lineTo(margin.left + width, floorY);
  ctx.stroke();
}

function drawBottomTicks(ctx, geometry, points) {
  const { margin, floorY, slotWidth } = geometry;
  ctx.fillStyle = "rgba(200,219,234,0.8)";
  ctx.font = "12px Segoe UI";

  monthlyTicks(points).forEach((tick) => {
    const x = margin.left + slotWidth * (tick.index + 0.5);
    ctx.fillText(tick.label, x - 8, floorY + 22);
  });
}

function drawTodayMarker(ctx, geometry, points, today) {
  const todayIndex = points.findIndex((item) => item.date === today);
  if (todayIndex < 0) {
    return;
  }
  const x = geometry.margin.left + geometry.slotWidth * (todayIndex + 0.5);
  ctx.strokeStyle = "rgba(255, 209, 107, 0.82)";
  ctx.setLineDash([5, 7]);
  ctx.beginPath();
  ctx.moveTo(x, geometry.margin.top);
  ctx.lineTo(x, geometry.floorY);
  ctx.stroke();
  ctx.setLineDash([]);
}

function drawProbabilityChart(payload) {
  const { ctx, cssWidth, cssHeight } = prepareCanvas(probabilityChart);
  const margin = { top: 28, right: 26, bottom: 48, left: 48 };
  const width = cssWidth - margin.left - margin.right;
  const height = cssHeight - margin.top - margin.bottom;
  const floorY = margin.top + height;
  const slotWidth = width / payload.predictions.length;
  const maxValue = Math.max(Math.max(...payload.predictions.map((item) => item.probability)) * 1.16, 0.06);

  const geometry = { margin, width, height, floorY, slotWidth, maxValue };

  const bg = ctx.createLinearGradient(0, margin.top, 0, floorY);
  bg.addColorStop(0, "rgba(104, 209, 255, 0.06)");
  bg.addColorStop(1, "rgba(104, 209, 255, 0)");
  ctx.fillStyle = bg;
  ctx.fillRect(margin.left, margin.top, width, height);

  drawGrid(ctx, geometry, maxValue, (value) => `${Math.round(value * 100)}%`);
  drawTodayMarker(ctx, geometry, payload.predictions, payload.today);

  const gradient = ctx.createLinearGradient(0, margin.top, 0, floorY);
  gradient.addColorStop(0, "#76dbff");
  gradient.addColorStop(0.55, "#39bcff");
  gradient.addColorStop(1, "#0f6cff");

  payload.predictions.forEach((point, index) => {
    const valueHeight = (point.probability / maxValue) * height;
    const x = margin.left + index * slotWidth;
    const y = floorY - valueHeight;
    ctx.fillStyle = gradient;
    ctx.fillRect(x + 0.35, y, Math.max(slotWidth - 0.7, 1), valueHeight);
  });

  drawBottomTicks(ctx, geometry, payload.predictions);
  chartState.set(probabilityChart.id, geometry);
}

function drawCountChart(canvas, payload, field, observedField, color, fillColor) {
  const { ctx, cssWidth, cssHeight } = prepareCanvas(canvas);
  const margin = { top: 22, right: 26, bottom: 42, left: 48 };
  const width = cssWidth - margin.left - margin.right;
  const height = cssHeight - margin.top - margin.bottom;
  const floorY = margin.top + height;
  const slotWidth = width / payload.predictions.length;
  const values = payload.predictions.map((item) => item[field]);
  const observedValues = payload.predictions.map((item) => item[observedField]).filter((value) => value !== null);
  const maxValue = Math.max(2, ...values, ...observedValues) * 1.16;
  const geometry = { margin, width, height, floorY, slotWidth, maxValue };

  const bg = ctx.createLinearGradient(0, margin.top, 0, floorY);
  bg.addColorStop(0, fillColor);
  bg.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = bg;
  ctx.fillRect(margin.left, margin.top, width, height);

  drawGrid(ctx, geometry, maxValue, (value) => `${value.toFixed(1)}`);
  drawTodayMarker(ctx, geometry, payload.predictions, payload.today);

  const linePoints = payload.predictions.map((point, index) => {
    const x = margin.left + slotWidth * (index + 0.5);
    const y = floorY - (point[field] / maxValue) * height;
    return { x, y, point };
  });

  ctx.beginPath();
  ctx.moveTo(linePoints[0].x, floorY);
  linePoints.forEach((point) => ctx.lineTo(point.x, point.y));
  ctx.lineTo(linePoints[linePoints.length - 1].x, floorY);
  ctx.closePath();
  ctx.fillStyle = fillColor;
  ctx.fill();

  ctx.strokeStyle = color;
  ctx.lineWidth = 2.5;
  ctx.beginPath();
  linePoints.forEach((point, index) => {
    if (index === 0) {
      ctx.moveTo(point.x, point.y);
    } else {
      ctx.lineTo(point.x, point.y);
    }
  });
  ctx.stroke();

  payload.predictions.forEach((point, index) => {
    if (point[observedField] === null) {
      return;
    }
    const x = margin.left + slotWidth * (index + 0.5);
    const y = floorY - (point[observedField] / maxValue) * height;
    ctx.fillStyle = "#eef7ff";
    ctx.beginPath();
    ctx.arc(x, y, 3.2, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.2;
    ctx.stroke();
  });

  drawBottomTicks(ctx, geometry, payload.predictions);
  chartState.set(canvas.id, geometry);
}

function buildBasis(rawFeatures, regression) {
  const stats = regression.stats;
  const air = (rawFeatures.airTemp - stats.means.airTemp) / stats.scales.airTemp;
  const sea = (rawFeatures.seaTemp - stats.means.seaTemp) / stats.scales.seaTemp;
  const moon = (rawFeatures.moonAge - stats.means.moonAge) / stats.scales.moonAge;
  return [1, air, sea, moon, air * sea, air * moon, sea * moon, air * air, sea * sea, moon * moon];
}

function dot(weights, vector) {
  return weights.reduce((sum, weight, index) => sum + weight * vector[index], 0);
}

function simulate(rawFeatures, payload) {
  const regression = payload.regression;
  const basis = buildBasis(rawFeatures, regression);
  const probability = clamp(dot(regression.models.probability.weights, basis), 0, 0.995);
  const predictedMin = clamp(Math.expm1(dot(regression.models.catchMin.weights, basis)), 0, regression.countCeiling);
  const predictedMaxRaw = clamp(Math.expm1(dot(regression.models.catchMax.weights, basis)), 0, regression.countCeiling);
  const predictedMax = Math.max(predictedMin, predictedMaxRaw);
  return { probability, predictedMin, predictedMax };
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
      <span class="detail">下限 ${countText(item.predictedMin)} / 上限 ${countText(item.predictedMax)}</span>
      <span class="subdetail">気温 ${item.airTemp.toFixed(1)}℃ / 水温 ${item.seaTemp.toFixed(1)}℃ / 月齢 ${item.moonAge.toFixed(1)}日</span>
    `;
    host.appendChild(chip);
  });
}

function configureSimulator(payload) {
  const update = () => {
    const rawFeatures = {
      airTemp: Number(simulatorNodes.airTemp.input.value),
      seaTemp: Number(simulatorNodes.seaTemp.input.value),
      moonAge: Number(simulatorNodes.moonAge.input.value),
    };

    Object.entries(simulatorNodes).forEach(([key, node]) => {
      node.value.textContent = formatControlValue(key, Number(node.input.value));
    });

    const result = simulate(rawFeatures, payload);
    outputNodes.probability.textContent = percent(result.probability);
    outputNodes.min.textContent = countText(result.predictedMin);
    outputNodes.max.textContent = countText(result.predictedMax);
  };

  if (!simulatorInitialized) {
    Object.entries(simulatorNodes).forEach(([key, node]) => {
      const config = payload.featureRanges[key];
      node.input.min = config.min;
      node.input.max = config.max;
      node.input.step = config.step;
      node.input.value = config.default;
      node.input.addEventListener("input", update);
    });
    simulatorInitialized = true;
  }

  update();
}

function showTooltip(canvas, tooltip, scroller, clientX, clientY) {
  if (!payloadState) {
    return;
  }

  const geometry = chartState.get(canvas.id);
  if (!geometry) {
    return;
  }

  const rect = canvas.getBoundingClientRect();
  const x = clientX - rect.left;
  const index = clamp(
    Math.floor((x - geometry.margin.left) / geometry.slotWidth),
    0,
    payloadState.predictions.length - 1,
  );
  const point = payloadState.predictions[index];
  if (!point) {
    tooltip.hidden = true;
    return;
  }

  tooltip.hidden = false;
  tooltip.style.left = `${Math.min(scroller.scrollLeft + x + 16, scroller.scrollLeft + rect.width - 228)}px`;
  tooltip.style.top = `${Math.max(16, clientY - rect.top - 120)}px`;
  tooltip.innerHTML = `
    <strong>${formatDate(point.date)}</strong>
    <span>Xデー確率 ${percent(point.probability)}</span>
    <span>下限 ${countText(point.predictedMin)} / 上限 ${countText(point.predictedMax)}</span>
    <span>気温 ${point.airTemp.toFixed(1)}℃ / 水温 ${point.seaTemp.toFixed(1)}℃ / 月齢 ${point.moonAge.toFixed(1)}日</span>
    <span>${point.fishNum ? `実績 ${point.fishNum}` : featureSourceLabel(point.featureSource)}</span>
  `;
}

function bindTooltip(canvasId, scrollerId, tooltipId) {
  const canvas = document.getElementById(canvasId);
  const scroller = document.getElementById(scrollerId);
  const tooltip = document.getElementById(tooltipId);

  const handleMove = (clientX, clientY) => showTooltip(canvas, tooltip, scroller, clientX, clientY);
  canvas.addEventListener("mousemove", (event) => handleMove(event.clientX, event.clientY));
  canvas.addEventListener(
    "touchmove",
    (event) => {
      const touch = event.touches[0];
      if (touch) {
        handleMove(touch.clientX, touch.clientY);
      }
    },
    { passive: true },
  );
  canvas.addEventListener("mouseleave", () => {
    tooltip.hidden = true;
  });
  canvas.addEventListener("touchend", () => {
    tooltip.hidden = true;
  });
}

function render(payload) {
  document.getElementById("title").textContent = `${payload.targetYear}年 トラフグXデー予測`;
  document.getElementById("generatedAt").textContent = `更新 ${payload.generatedAt}`;
  document.getElementById("threshold").textContent = `Xデー閾値 ${payload.xDayThreshold}匹以上`;
  document.getElementById("rangeLabel").textContent = `${payload.seasonRange.from} - ${payload.seasonRange.to}`;
  document.getElementById("todayLabel").textContent = `基準日 ${payload.today}`;

  populateTopDays(payload);
  configureSimulator(payload);
  drawProbabilityChart(payload);
  drawCountChart(minChart, payload, "predictedMin", "observedMin", "#4ff0c6", "rgba(79, 240, 198, 0.22)");
  drawCountChart(maxChart, payload, "predictedMax", "observedMax", "#ffd16b", "rgba(255, 209, 107, 0.20)");
}

bindTooltip("probChart", "probChartScroller", "probTooltip");
bindTooltip("minChart", "minChartScroller", "minTooltip");
bindTooltip("maxChart", "maxChartScroller", "maxTooltip");

window.addEventListener("resize", () => {
  if (payloadState) {
    render(payloadState);
  }
});

async function main() {
  const response = await fetch("./data/predictions.json");
  payloadState = await response.json();
  render(payloadState);
}

main().catch((error) => {
  console.error(error);
});
