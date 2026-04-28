(function () {
  const COLORS = {
    claim: "#8b5cf6",
    amplifier: "#f59e0b",
    verification: "#2563eb",
    observer: "#94a3b8",
  };

  const LABELS = {
    claim: "Original Claim",
    amplifier: "Hype Amplifiers",
    verification: "Verification",
    observer: "Observers / Explainers",
  };

  const KEY_EVENTS = [
    { hour: 0, label: "Initial\nburst" },
    { hour: 6, label: "Authority\npush" },
    { hour: 12, label: "Evidence\npressure" },
    { hour: 19, label: "Consensus\nshift" },
  ];

  function normalizeRows(rows) {
    const rowMap = new Map(rows.map((row) => [row.hour, row]));
    const maxHour = rows.length > 0 ? Math.max(23, ...rows.map((row) => row.hour)) : 23;

    return Array.from({ length: maxHour + 1 }, (_, hour) => {
      const row = rowMap.get(hour) || {};
      return {
        hour,
        claim: row.claim || 0,
        amplifier: row.amplifier || 0,
        verification: row.verification || 0,
        observer: row.observer || 0,
      };
    });
  }

  function buildOption(rows, platform) {
    const normalized = normalizeRows(rows);
    const hours = normalized.map((row) => row.hour);
    const roles = ["claim", "amplifier", "verification", "observer"];

    const series = roles.map((role) => ({
      name: LABELS[role],
      type: "line",
      stack: "total",
      areaStyle: { opacity: 0.88 },
      smooth: true,
      symbol: "none",
      lineStyle: { width: 1.5, color: COLORS[role] },
      color: COLORS[role],
      data: normalized.map((row) => row[role]),
      emphasis: { focus: "series" },
    }));

    if (series[0]) {
      series[0].markLine = {
        silent: true,
        symbol: "none",
        data: KEY_EVENTS.map((event) => ({
          xAxis: event.hour,
          label: {
            formatter: event.label,
            position: "insideEndTop",
            color: "#78716c",
            fontSize: 10,
            lineHeight: 12,
          },
          lineStyle: {
            color: "#d6d3d1",
            type: "dashed",
            width: 1,
          },
        })),
      };
    }

    return {
      animationDuration: 900,
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "cross" },
        formatter(params) {
          const hour = params[0]?.axisValueLabel ?? params[0]?.axisValue ?? "";
          const title = platform === "twitter" ? "Twitter" : "Reddit";
          let html = `<b>${title} · H${hour}</b><br/>`;
          params.forEach((param) => {
            html += `<span style="color:${param.color}">●</span> ${param.seriesName}: <b>${param.value}</b><br/>`;
          });
          return html;
        },
      },
      legend: {
        bottom: 0,
        icon: "roundRect",
        itemWidth: 12,
        itemHeight: 8,
        textStyle: {
          color: "#44403c",
          fontSize: 12,
        },
      },
      grid: {
        top: 26,
        left: 10,
        right: 12,
        bottom: 52,
        containLabel: true,
      },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: hours,
        axisLine: { lineStyle: { color: "#d6d3d1" } },
        axisTick: { show: false },
        axisLabel: {
          color: "#78716c",
          fontSize: 11,
          formatter(value) {
            return `H${value}`;
          },
        },
      },
      yAxis: {
        type: "value",
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: {
          color: "#78716c",
          fontSize: 11,
        },
        splitLine: {
          lineStyle: {
            color: "#f5f5f4",
          },
        },
      },
      series,
    };
  }

  window.initOpinionChart = function (containerId, platform, data) {
    const el = document.getElementById(containerId);
    if (!el || typeof echarts === "undefined") {
      return;
    }

    const chart = echarts.init(el, null, { renderer: "svg" });
    chart.setOption(buildOption(data[platform] || [], platform));
    window.addEventListener("resize", () => chart.resize());
  };
})();
