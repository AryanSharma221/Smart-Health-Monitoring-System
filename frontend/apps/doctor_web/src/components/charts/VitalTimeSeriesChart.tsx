import React, { useState, useMemo } from 'react';
import type { VitalsReading, MetricCode } from '../../types';
import { formatVitalValue, formatTimestamp } from '../../utils';
import { EmptyState, LoadingIndicator } from '../ui';
import styles from './VitalTimeSeriesChart.module.css';

interface VitalTimeSeriesChartProps {
  readings: VitalsReading[];
  metricCode: MetricCode;
  metricLabel: string;
  metricUnit: string;
  timeRangeDescription: string;
  isLoading?: boolean;
}

interface PlottedPoint {
  index: number;
  reading: VitalsReading;
  cx: number;
  cy: number;
  timeMs: number;
  val: number;
}

function formatShortTimeTick(ms: number): string {
  const d = new Date(ms);
  if (isNaN(d.getTime())) return '';
  return d.toLocaleDateString('en-US', {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

export const VitalTimeSeriesChart: React.FC<VitalTimeSeriesChartProps> = ({
  readings,
  metricLabel,
  metricUnit,
  timeRangeDescription,
  isLoading = false,
}) => {
  const [activePoint, setActivePoint] = useState<PlottedPoint | null>(null);
  const [showTable, setShowTable] = useState<boolean>(false);

  // SVG Chart Geometry Dimensions
  const svgWidth = 800;
  const svgHeight = 320;
  const padding = { top: 25, right: 30, bottom: 45, left: 60 };
  const chartWidth = svgWidth - padding.left - padding.right;
  const chartHeight = svgHeight - padding.top - padding.bottom;

  // Filter, Deduplicate & Sort valid data points chronologically
  const sortedValidReadings = useMemo(() => {
    const valid = readings.filter(
      (r) =>
        r.value !== null &&
        r.value !== undefined &&
        !isNaN(r.value) &&
        r.measuredAt !== null &&
        r.measuredAt !== undefined
    );

    // Prevent repeated points from duplicate polling responses (deduplicate by eventId or metric:time:value)
    const seen = new Set<string>();
    const deduplicated: VitalsReading[] = [];
    for (const r of valid) {
      const key = r.eventId ? `${r.metricCode}:${r.eventId}` : `${r.metricCode}:${r.measuredAt}:${r.value}`;
      if (!seen.has(key)) {
        seen.add(key);
        deduplicated.push(r);
      }
    }

    return deduplicated.sort((a, b) => {
      const timeA = new Date(a.measuredAt!).getTime() || 0;
      const timeB = new Date(b.measuredAt!).getTime() || 0;
      return timeA - timeB;
    });
  }, [readings]);

  // Compute Scales, Paths, and Points
  const { points, linePath, areaPath, yTicks, xTicks, minVal, maxVal } = useMemo(() => {
    if (sortedValidReadings.length === 0) {
      return {
        points: [],
        linePath: '',
        areaPath: '',
        yTicks: [],
        xTicks: [],
        minVal: 0,
        maxVal: 100,
      };
    }

    // Determine Y Bounds (min & max values)
    const vals = sortedValidReadings.map((r) => r.value!);
    let min = Math.min(...vals);
    let max = Math.max(...vals);

    if (min === max) {
      min = min - 5;
      max = max + 5;
    } else {
      // 8% margin padding
      const margin = (max - min) * 0.08;
      min = Math.floor(min - margin);
      max = Math.ceil(max + margin);
    }

    // Determine X Bounds (time in ms)
    const times = sortedValidReadings.map((r) => new Date(r.measuredAt!).getTime());
    const minTime = Math.min(...times);
    const maxTime = Math.max(...times);
    const isSinglePoint = minTime === maxTime;

    // Generate Points coordinates
    const plotted: PlottedPoint[] = sortedValidReadings.map((reading, index) => {
      const timeMs = new Date(reading.measuredAt!).getTime();
      const val = reading.value!;

      const cx = isSinglePoint
        ? padding.left + chartWidth / 2
        : padding.left + ((timeMs - minTime) / (maxTime - minTime)) * chartWidth;

      const cy =
        padding.top + chartHeight - ((val - min) / (max - min)) * chartHeight;

      return {
        index,
        reading,
        cx,
        cy,
        timeMs,
        val,
      };
    });

    // Build SVG Path strings with honest gap detection (no interpolation across gaps > 20 mins)
    const GAP_THRESHOLD_MS = 20 * 60 * 1000;
    let pathD = '';
    let hasGap = false;
    for (let i = 0; i < plotted.length; i++) {
      const pt = plotted[i];
      if (i === 0) {
        pathD = `M ${pt.cx.toFixed(1)},${pt.cy.toFixed(1)}`;
      } else {
        const prevPt = plotted[i - 1];
        const gap = pt.timeMs - prevPt.timeMs;
        if (gap > GAP_THRESHOLD_MS) {
          hasGap = true;
          pathD += ` M ${pt.cx.toFixed(1)},${pt.cy.toFixed(1)}`;
        } else {
          pathD += ` L ${pt.cx.toFixed(1)},${pt.cy.toFixed(1)}`;
        }
      }
    }

    const bottomY = padding.top + chartHeight;
    const firstX = plotted[0].cx.toFixed(1);
    const lastX = plotted[plotted.length - 1].cx.toFixed(1);
    const areaD = hasGap ? '' : `${pathD} L ${lastX},${bottomY} L ${firstX},${bottomY} Z`;

    // 4 Y-Axis Ticks
    const ticksCountY = 4;
    const yTickValues: { val: number; y: number }[] = [];
    for (let i = 0; i < ticksCountY; i++) {
      const tickVal = min + (i / (ticksCountY - 1)) * (max - min);
      const y = padding.top + chartHeight - (i / (ticksCountY - 1)) * chartHeight;
      yTickValues.push({ val: Math.round(tickVal * 10) / 10, y });
    }

    // 4 X-Axis Ticks
    const xTickValues: { timeMs: number; x: number }[] = [];
    if (isSinglePoint) {
      xTickValues.push({ timeMs: minTime, x: padding.left + chartWidth / 2 });
    } else {
      const ticksCountX = 4;
      for (let i = 0; i < ticksCountX; i++) {
        const timeMs = minTime + (i / (ticksCountX - 1)) * (maxTime - minTime);
        const x = padding.left + (i / (ticksCountX - 1)) * chartWidth;
        xTickValues.push({ timeMs, x });
      }
    }

    return {
      points: plotted,
      linePath: pathD,
      areaPath: areaD,
      yTicks: yTickValues,
      xTicks: xTickValues,
      minVal: min,
      maxVal: max,
    };
  }, [sortedValidReadings, chartWidth, chartHeight, padding.left, padding.top]);

  if (isLoading) {
    return (
      <div className={styles.chartContainer}>
        <div style={{ padding: '48px 0', textAlign: 'center' }}>
          <LoadingIndicator label={`Querying ${metricLabel} historical stream…`} />
        </div>
      </div>
    );
  }

  if (sortedValidReadings.length === 0) {
    return (
      <div className={styles.chartContainer}>
        <div className={styles.chartHeader}>
          <div className={styles.chartTitleCol}>
            <h3 className={styles.chartTitle}>{metricLabel} Historical Trajectory</h3>
            <p className={styles.chartMetaText}>Window: {timeRangeDescription}</p>
          </div>
        </div>
        <EmptyState
          preset="no_history"
          title={`No ${metricLabel} History in Selected Interval`}
          description={`No recorded measurements exist for ${metricLabel} during this time range. Historical Kaggle CSV entries are archived from October 2023.`}
        />
      </div>
    );
  }

  return (
    <div className={styles.chartContainer}>
      {/* Chart Title and Header Meta */}
      <div className={styles.chartHeader}>
        <div className={styles.chartTitleCol}>
          <h3 className={styles.chartTitle}>
            <span>{metricLabel}</span>
            <span style={{ fontSize: '13px', fontWeight: 500, color: 'var(--color-text-muted)' }}>
              ({metricUnit})
            </span>
          </h3>
          <p className={styles.chartMetaText}>
            Showing {points.length} measurements · Range: {timeRangeDescription} · Baseline: [{minVal} – {maxVal} {metricUnit}]
          </p>
        </div>

        <div className={styles.chartControls}>
          <button
            type="button"
            className={styles.accessibleTableToggleBtn}
            onClick={() => setShowTable((prev) => !prev)}
            aria-expanded={showTable}
            aria-controls="accessible-chart-data-table"
          >
            {showTable ? 'Hide Tabular Data' : 'View Tabular Data (Accessibility)'}
          </button>
        </div>
      </div>

      {/* SVG Vector Chart Canvas */}
      <div className={styles.chartSvgWrapper}>
        {/* Floating Tooltip details if point is active */}
        {activePoint && (
          <div className={styles.tooltipOverlay} role="tooltip">
            <span className={styles.tooltipProvenance}>
              {activePoint.reading.isSimulated
                ? 'SIMULATED SMARTWATCH (SYNTHETIC)'
                : 'KAGGLE HISTORICAL RECORD (ARCHIVE)'}
            </span>
            <div className={styles.tooltipValueRow}>
              <span className={styles.tooltipValue}>
                {formatVitalValue(activePoint.val, metricUnit as any)}
              </span>
              <span style={{ color: 'var(--color-nav-text-secondary)', fontSize: '11px' }}>
                ({metricLabel})
              </span>
            </div>
            <span className={styles.tooltipTimestamp}>
              {formatTimestamp(activePoint.reading.measuredAt)}
            </span>
          </div>
        )}

        <svg
          viewBox={`0 0 ${svgWidth} ${svgHeight}`}
          className={styles.svgElement}
          role="img"
          aria-label={`Time series trajectory of ${metricLabel} over ${timeRangeDescription}`}
        >
          <defs>
            <linearGradient id="chartGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--color-primary)" stopOpacity="0.3" />
              <stop offset="100%" stopColor="var(--color-primary)" stopOpacity="0.0" />
            </linearGradient>
          </defs>

          {/* Horizontal Gridlines and Y Ticks */}
          {yTicks.map((tick, idx) => (
            <g key={`ytick-${idx}`}>
              <line
                x1={padding.left}
                y1={tick.y}
                x2={padding.left + chartWidth}
                y2={tick.y}
                className={styles.gridLine}
              />
              <text
                x={padding.left - 10}
                y={tick.y + 4}
                className={`${styles.axisTickText} ${styles.axisTickTextY}`}
              >
                {tick.val}
              </text>
            </g>
          ))}

          {/* Axes Lines */}
          <line
            x1={padding.left}
            y1={padding.top}
            x2={padding.left}
            y2={padding.top + chartHeight}
            className={styles.axisLine}
          />
          <line
            x1={padding.left}
            y1={padding.top + chartHeight}
            x2={padding.left + chartWidth}
            y2={padding.top + chartHeight}
            className={styles.axisLine}
          />

          {/* X Axis Time Ticks */}
          {xTicks.map((tick, idx) => (
            <g key={`xtick-${idx}`}>
              <line
                x1={tick.x}
                y1={padding.top + chartHeight}
                x2={tick.x}
                y2={padding.top + chartHeight + 6}
                className={styles.axisLine}
              />
              <text
                x={tick.x}
                y={padding.top + chartHeight + 20}
                className={`${styles.axisTickText} ${styles.axisTickTextX}`}
              >
                {formatShortTimeTick(tick.timeMs)}
              </text>
            </g>
          ))}

          {/* Gradient Area Fill */}
          {areaPath && <path d={areaPath} className={styles.dataArea} />}

          {/* Connecting Data Line */}
          {linePath && <path d={linePath} className={styles.dataLine} />}

          {/* Interactive Data Point Circles */}
          {points.map((pt) => {
            const isActive = activePoint?.index === pt.index;
            return (
              <circle
                key={`point-${pt.index}`}
                cx={pt.cx}
                cy={pt.cy}
                r={isActive ? 6.5 : 4}
                className={`${styles.dataPoint} ${isActive ? styles.activePoint : ''}`}
                tabIndex={0}
                role="graphics-symbol"
                aria-label={`${formatVitalValue(pt.val, metricUnit as any)} measured on ${formatTimestamp(
                  pt.reading.measuredAt
                )}`}
                onMouseEnter={() => setActivePoint(pt)}
                onMouseLeave={() => setActivePoint(null)}
                onFocus={() => setActivePoint(pt)}
                onBlur={() => setActivePoint(null)}
              />
            );
          })}
        </svg>
      </div>

      {/* Accessible Tabular Data for Screen Readers / High Information Density */}
      {showTable && (
        <div id="accessible-chart-data-table" className={styles.accessibleTableWrapper}>
          <table className={styles.dataTable}>
            <thead>
              <tr>
                <th>Measured Timestamp</th>
                <th>{metricLabel} Value</th>
                <th>Unit</th>
                <th>Provenance Source</th>
                <th>Freshness State</th>
              </tr>
            </thead>
            <tbody>
              {sortedValidReadings.map((r, i) => (
                <tr key={`tab-row-${i}`}>
                  <td>{formatTimestamp(r.measuredAt)}</td>
                  <td>{formatVitalValue(r.value, metricUnit as any)}</td>
                  <td>{metricUnit}</td>
                  <td>{r.source === 'kaggle_csv' ? 'Kaggle Dataset' : 'Live Simulator'}</td>
                  <td>{r.freshness}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
