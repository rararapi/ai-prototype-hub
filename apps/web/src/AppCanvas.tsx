import type { AiConfig } from './ai-client';
import './demo-studio.css';

export default function AppCanvas({ config, standalone = false }: { config: AiConfig; standalone?: boolean }) {
  const Heading = standalone ? 'h1' : 'h3';
  const management = config.template === 'management-dashboard';
  return <section className={`demo-canvas theme-${config.color}`} aria-label="Gemini画面見本" data-testid="ai-canvas">
    <div className="canvas-toolbar"><span className="canvas-logo" aria-hidden="true">{management ? '▥' : 'H'}</span>
      <span>{management ? '経営管理' : 'Hello Web'}</span><span className="sample-data">架空のサンプルデータ</span></div>
    <div className="canvas-body">
      <div className="canvas-heading"><div><Heading>{config.title}</Heading><p>{config.subtitle}</p></div>
        {management && <span className="canvas-period">10月の予実</span>}</div>
      {management ? <>
        <div className="management-metrics">
          {[['売上', '¥128,000,000', '予算 ¥120,000,000', '予算比 +6.7%'],
            ['費用', '¥96,000,000', '予算 ¥94,000,000', '予算比 +2.1%'],
            ['営業利益', '¥32,000,000', '予算 ¥26,000,000', '予算比 +23.1%'],
            ['営業利益率', '25.0%', '予算 21.7%', '予算比 +3.3ポイント'],
            ...(config.cash_flow ? [['営業キャッシュフロー', '¥18,600,000', '前月 ¥16,200,000', '前月比 +14.8%']] : [])].map(([label, value, note, comparison]) =>
            <div className="management-metric" key={label}><span>{label}</span><strong>{value}</strong><small>{note}</small><span className="metric-comparison">{comparison}</span></div>)}
        </div>
        {config.trend && <section className="canvas-section" aria-labelledby="trend-heading"><h4 id="trend-heading">売上・利益推移</h4>
          <p className="chart-description">5月→10月の架空データ。売上 7,500万円→12,800万円 / 営業利益 1,200万円→3,200万円。</p>
          <svg className="demo-chart" viewBox="0 0 600 150" role="img" aria-label="売上は5月7500万円から10月12800万円、営業利益は1200万円から3200万円への6か月推移">
            <path className="chart-grid" d="M20 30H580 M20 75H580 M20 120H580" />
            <path className="chart-area" d="M20 65L132 56L244 50L356 35L468 22L580 10V140H20Z" />
            <path className="chart-line" d="M20 65L132 56L244 50L356 35L468 22L580 10" />
            <path className="chart-profit" d="M20 129L132 125L244 121L356 117L468 112L580 108" />
          </svg><div className="chart-months"><span>5月</span><span>6月</span><span>7月</span><span>8月</span><span>9月</span><span>10月</span></div>
          <div className="chart-legend"><span>実線：売上</span><span>破線：営業利益</span></div>
        </section>}
        {config.departments && <section className="canvas-section"><h4>部門別の予実</h4>
          <div className="demo-table-scroll"><table className="demo-table"><caption className="sr-only">架空の部門別売上・利益・予算達成率</caption>
            <thead><tr><th scope="col">部門</th><th scope="col">売上</th><th scope="col">営業利益</th><th scope="col">売上予算比</th></tr></thead>
            <tbody>{[['事業A','¥62,000,000','¥18,600,000','103%'],['事業B','¥41,000,000','¥9,020,000','117%'],['事業C','¥25,000,000','¥4,380,000','100%']].map(row =>
              <tr key={row[0]}>{row.map((cell,index) => index === 0 ? <th key={cell} scope="row">{cell}</th> : <td key={cell}>{cell}</td>)}</tr>)}</tbody>
          </table></div></section>}
        {!config.trend && !config.departments && <div className="canvas-tip">AIへの追加指示で、利益推移グラフや部門別の表を加えられます。</div>}
      </> : <div className="hello-content"><span className="hello-symbol" aria-hidden="true">✦</span>
        <p>あなたのアイデアの、最初の画面。</p><p>タイトルや説明、配色をAIへの指示で変えてみましょう。</p></div>}
    </div>
  </section>;
}
