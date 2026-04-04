import React, { useState } from 'react';
import { Activity, Layout, Layers, Terminal as TermIcon, Settings, Search, Menu, Maximize2 } from 'lucide-react';

// Modular Component Registry (Placeholders for now)
const Watchlist = () => (
  <div className="module-content animate-in">
    <div className="flex border-b border-gray-800 pb-2 mb-2 justify-between items-center text-xs text-gray-500">
      <span>TICKER</span>
      <span>PRICE</span>
      <span>CHANGE</span>
    </div>
    {[
      { s: 'GGAL', p: '245.50', c: '+1.2%' },
      { s: 'AL30D', p: '45.12', c: '+0.5%' },
      { s: 'BTCUSDT', p: '67,420.0', c: '-0.3%' },
      { s: 'SPX', p: '5,254.3', c: '+0.1%' },
    ].map((item, idx) => (
      <div key={idx} className="flex justify-between items-center py-2 text-sm border-b border-gray-800/50 hover:bg-white/5 px-1 rounded cursor-pointer transition-colors">
        <span className="font-bold">{item.s}</span>
        <span className="font-mono">{item.p}</span>
        <span className={item.c.startsWith('+') ? 'text-green-500' : 'text-red-500'}>{item.c}</span>
      </div>
    ))}
  </div>
);

const OptionMatrix = () => (
  <div className="module-content animate-in font-mono">
    <div className="grid grid-cols-5 gap-1 text-[10px] text-gray-600 mb-2 font-bold uppercase text-center border-b border-gray-800 pb-1">
      <div>Strike</div>
      <div>Bid (C)</div>
      <div>Ask (C)</div>
      <div>Delta</div>
      <div>Gamma</div>
    </div>
    {[100, 105, 110, 115, 120].map((strike) => (
      <div key={strike} className="grid grid-cols-5 gap-1 text-xs py-1 hover:bg-blue-500/10 cursor-pointer border-b border-gray-900">
        <div className="text-center font-bold text-gray-400">{strike}</div>
        <div className="text-center text-green-400">1.45</div>
        <div className="text-center text-green-400">1.48</div>
        <div className="text-center text-blue-400">0.52</div>
        <div className="text-center text-purple-400">0.12</div>
      </div>
    ))}
    <div className="mt-4 p-2 bg-blue-500/5 rounded border border-blue-500/20 text-[10px] text-gray-400 italic">
      Real-time Greeks calculated via BS Engine
    </div>
  </div>
);

const MarketDepth = () => (
  <div className="module-content animate-in">
    <div className="flex justify-between items-center mb-4 text-xs">
      <span className="bg-red-500/20 text-red-400 px-2 rounded">Bids</span>
      <span className="font-display font-bold">GGAL</span>
      <span className="bg-green-500/20 text-green-400 px-2 rounded">Asks</span>
    </div>
    <div className="flex gap-2 h-full pb-8">
      <div className="flex-1 space-y-1">
        {[245.5, 245.4, 245.3, 245.2, 245.1].map(p => (
          <div key={p} className="flex justify-between items-center text-[10px] bg-red-900/10 p-1 rounded">
            <span>{p.toFixed(2)}</span>
            <span className="font-bold">1.2k</span>
          </div>
        ))}
      </div>
      <div className="flex-1 space-y-1">
        {[245.6, 245.7, 245.8, 245.9, 246.0].map(p => (
          <div key={p} className="flex justify-between items-center text-[10px] bg-green-900/10 p-1 rounded">
            <span className="font-bold">0.8k</span>
            <span>{p.toFixed(2)}</span>
          </div>
        ))}
      </div>
    </div>
  </div>
);

const NewsAggr = () => (
  <div className="module-content animate-in text-xs space-y-3">
    {[
      { t: '10:42', i: 'GGAL', d: 'Relevant Fact: Quarterly dividend approval' },
      { t: '09:15', i: 'BYMA', d: 'New listing: Treasury Bill Z20F6' },
      { t: 'Yesterday', i: 'AL30', d: 'Coupon payment confirmation' },
    ].map((n, i) => (
      <div key={i} className="border-l-2 border-blue-500 pl-2 py-1 hover:bg-white/5 cursor-pointer">
        <div className="flex justify-between text-[10px] text-gray-500">
          <span>{n.i}</span>
          <span>{n.t}</span>
        </div>
        <p className="line-clamp-2">{n.d}</p>
      </div>
    ))}
  </div>
);

function App() {
  const [activeTab, setActiveTab] = useState('portfolio');

  return (
    <div className="flex flex-col h-screen w-screen overflow-hidden text-gray-100 selection:bg-blue-500/30">
      {/* Top Bar Navigation */}
      <header className="app-header">
        <div className="flex items-center gap-6">
          <span className="brand flex items-center gap-2">
            <TermIcon size={18} />
            TWS TERMINAL
          </span>
          <nav className="flex gap-4">
            {['Portfolio', 'Research', 'Options', 'Futures'].map(tab => (
              <button 
                key={tab} 
                onClick={() => setActiveTab(tab.toLowerCase())}
                className={`text-[11px] font-bold uppercase transition-all pb-1 border-b-2 ${activeTab === tab.toLowerCase() ? 'border-blue-500 text-white' : 'border-transparent text-gray-500 hover:text-gray-300'}`}
              >
                {tab}
              </button>
            ))}
          </nav>
        </div>
        <div className="flex items-center gap-4 text-gray-400">
          <div className="relative group">
            <Search size={14} className="absolute left-2 top-1/2 -translate-y-1/2" />
            <input 
              type="text" 
              placeholder="Search ticker..." 
              className="bg-black/40 border border-gray-800 rounded-full pl-8 pr-4 py-1 text-xs focus:outline-none focus:border-blue-500 w-48"
            />
          </div>
          <Activity size={16} className="text-green-500" />
          <Settings size={16} className="hover:text-white cursor-pointer transition-colors" />
        </div>
      </header>

      {/* Main Grid Workspace */}
      <main className="dashboard-container">
        {/* Left Side: Market Info */}
        <section className="flex flex-col gap-px h-full">
          <div className="module flex-1">
            <div className="module-header"><Layout size={12} className="mr-2" /> Watchlist</div>
            <Watchlist />
          </div>
          <div className="module h-1/3">
             <div className="module-header"><Layers size={12} className="mr-2" /> Recent News</div>
             <NewsAggr />
          </div>
        </section>

        {/* Center: Primary Analysis */}
        <section className="flex flex-col gap-px h-full">
          <div className="module flex-1">
            <div className="module-header flex justify-between w-full">
              <span className="flex items-center"><Maximize2 size={12} className="mr-2" /> Option Matrix - MARCH 2026</span>
              <span className="text-blue-400">GGAL.BA</span>
            </div>
            <OptionMatrix />
          </div>
          <div className="module h-1/4">
             <div className="module-header">Futures Curve - CCL/DLR</div>
             <div className="module-content flex items-center justify-center text-gray-600 italic">
               Curve visualization module initializing...
             </div>
          </div>
        </section>

        {/* Right Side: Depth & Execution */}
        <section className="flex flex-col gap-px h-full">
          <div className="module flex-1">
            <div className="module-header">Market Depth (DOM)</div>
            <MarketDepth />
          </div>
          <div className="module h-1/2 bg-blue-900/5">
             <div className="module-header">Quick Order Entry</div>
             <div className="module-content p-4 space-y-4">
                <div className="flex gap-2">
                  <button className="flex-1 bg-green-600 hover:bg-green-500 py-3 rounded font-bold text-xs">BUY</button>
                  <button className="flex-1 bg-red-600 hover:bg-red-500 py-3 rounded font-bold text-xs">SELL</button>
                </div>
                <div className="space-y-1">
                  <label className="text-[10px] text-gray-500 uppercase font-bold">Quantity</label>
                  <input type="number" defaultValue={100} className="w-full bg-black/50 border border-gray-800 p-2 rounded text-sm focus:outline-none focus:border-blue-500" />
                </div>
                <div className="space-y-1">
                  <label className="text-[10px] text-gray-500 uppercase font-bold">Limit Price</label>
                  <input type="number" defaultValue={245.50} step="0.01" className="w-full bg-black/50 border border-gray-800 p-2 rounded text-sm focus:outline-none focus:border-blue-500" />
                </div>
             </div>
          </div>
        </section>
      </main>

      {/* Footer Status Bar */}
      <footer className="h-6 bg-black border-t border-gray-800 px-4 flex items-center justify-between text-[10px] text-gray-500">
        <div className="flex gap-4">
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-green-500"></span> BYMA CONNECTED</span>
          <span>SRV-SCRAPING-PROXY: ONLINE</span>
        </div>
        <div className="flex gap-2">
          <span>UTC: {new Date().toISOString().substring(11, 19)}</span>
          <span className="text-gray-400 font-bold">v1.2.0-Alpha</span>
        </div>
      </footer>
    </div>
  );
}

export default App;
