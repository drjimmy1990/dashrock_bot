import { useState, useEffect, useRef } from 'react';
import { createChart, ColorType, CrosshairMode, CandlestickSeries, LineStyle } from 'lightweight-charts';
import { api } from '../services/api';

export default function ChartPage() {
  const chartRef = useRef(null);
  const chartInstance = useRef(null);
  const seriesRef = useRef(null);
  const priceLinesRef = useRef([]);
  const [symbols, setSymbols] = useState([]);
  const [active, setActive] = useState('');

  useEffect(() => {
    api.watchlist().then(d => {
      setSymbols(d.symbols || []);
      // Default to first trade_list symbol (has WS candle data), not first watchlist symbol
      const defaultSym = d.trade_list?.[0] || d.symbols?.[0] || '';
      setActive(defaultSym);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!chartRef.current || !active) return;
    if (chartInstance.current) chartInstance.current.remove();

    const chart = createChart(chartRef.current, {
      layout: { background: { type: ColorType.Solid, color: '#111827' }, textColor: '#94a3b8' },
      grid: { vertLines: { color: 'rgba(255,255,255,0.04)' }, horzLines: { color: 'rgba(255,255,255,0.04)' } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.08)' },
      timeScale: {
        borderColor: 'rgba(255,255,255,0.08)',
        timeVisible: true,
        rightOffset: 5,
        shiftVisibleRangeOnNewBar: true,
      },
      width: chartRef.current.clientWidth,
      height: 500,
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: '#10b981', downColor: '#ef4444',
      borderUpColor: '#10b981', borderDownColor: '#ef4444',
      wickUpColor: '#10b981', wickDownColor: '#ef4444',
    });
    chartInstance.current = chart;
    seriesRef.current = series;
    priceLinesRef.current = [];

    let cancelled = false;
    let lastDataJson = '';

    // Map lineStyle numbers from backend to lightweight-charts LineStyle
    const styleMap = { 0: LineStyle.Solid, 1: LineStyle.Dotted, 2: LineStyle.Dashed };

    const loadCandles = () => {
      if (cancelled) return;
      api.candles(active, 300).then(data => {
        if (cancelled || !data.length) return;

        const newJson = JSON.stringify(data);
        if (newJson === lastDataJson) return;

        const prevData = lastDataJson ? JSON.parse(lastDataJson) : [];
        const onlyLastChanged = prevData.length === data.length
          && prevData.length > 0
          && JSON.stringify(prevData.slice(0, -1)) === JSON.stringify(data.slice(0, -1));

        if (onlyLastChanged && prevData.length > 0) {
          series.update(data[data.length - 1]);
        } else {
          series.setData(data);
          if (!lastDataJson) {
            chart.timeScale().scrollToRealTime();
          }
        }
        lastDataJson = newJson;
      }).catch(err => {
        console.warn('[Chart] poll error:', err.message);
      });
    };

    const loadLevels = () => {
      if (cancelled) return;
      api.levels(active).then(resp => {
        if (cancelled) return;
        // Remove old price lines
        for (const pl of priceLinesRef.current) {
          try { series.removePriceLine(pl); } catch {}
        }
        priceLinesRef.current = [];

        // Draw new price lines
        for (const lvl of (resp.levels || [])) {
          const pl = series.createPriceLine({
            price: lvl.price,
            color: lvl.color,
            lineWidth: 1,
            lineStyle: styleMap[lvl.style] ?? LineStyle.Dashed,
            axisLabelVisible: true,
            title: lvl.title,
          });
          priceLinesRef.current.push(pl);
        }
      }).catch(() => {});
    };

    // Initial load + poll
    loadCandles();
    loadLevels();
    const candleTimer = setInterval(loadCandles, 2000);
    const levelsTimer = setInterval(loadLevels, 3000);

    const handleResize = () => chart.applyOptions({ width: chartRef.current?.clientWidth || 800 });
    window.addEventListener('resize', handleResize);
    return () => {
      cancelled = true;
      clearInterval(candleTimer);
      clearInterval(levelsTimer);
      window.removeEventListener('resize', handleResize);
      chart.remove();
      chartInstance.current = null;
    };
  }, [active]);

  return (
    <>
      <div className="page-header">
        <div><h2>Chart</h2><div className="subtitle">{active || 'Select a symbol'}</div></div>
        <div style={{ display: 'flex', gap: 6 }}>
          {symbols.map(s => (
            <button key={s} className={`btn btn-sm ${s === active ? 'btn-primary' : 'btn-outline'}`} onClick={() => setActive(s)}>{s.replace('USDT', '')}</button>
          ))}
        </div>
      </div>
      <div className="page-content">
        <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
          <div ref={chartRef} style={{ width: '100%', height: 500 }} />
        </div>
        <div style={{ display: 'flex', gap: 16, marginTop: 12, flexWrap: 'wrap', fontSize: '0.8rem' }}>
          <span style={{ color: '#10b981' }}>━━ Buy Stop</span>
          <span style={{ color: '#ef4444' }}>━━ Sell Stop</span>
          <span style={{ color: '#f59e0b' }}>┈┈ Stop Loss</span>
          <span style={{ color: '#3b82f6' }}>┈┈ Take Profit</span>
          <span style={{ color: '#8b5cf6' }}>── Entry</span>
          <span style={{ color: '#ec4899' }}>━━ Trailing HW</span>
        </div>
      </div>
    </>
  );
}
