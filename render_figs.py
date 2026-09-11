#!/usr/bin/env python3
"""把配图页里的 <svg> 导出成静态 SVG + PNG，供成品 .md 引用。

为什么需要它：手绘图是 rough.js 在浏览器里现画的，DOM 里才有形状，文件里只有一段
脚本。要把图放进公众号 / Notion / Blog，必须先落成静态文件。手动截图会掉字体、
掉分辨率、每次尺寸还不一样，所以这里走「浏览器渲染一次，按 viewBox 精确导出」。

做法：本脚本起一个临时本地服务器，把配图页喂给浏览器；页面里注入的导出脚本把每个
<svg> 序列化（连同内联的 @font-face 一起塞进 SVG 内部，脱离页面也不掉字），再用
canvas 按倍率栅格化成 PNG，POST 回来落盘。全程本地，不依赖 Chrome headless、
Playwright、cairo 这类外部渲染器。

用法：
    python3 render_figs.py "output/<标题>/图解.html" --out "output/<标题>/figs"
    python3 render_figs.py 页面.html --out figs --scale 3 --no-open

--scale 2 的输出宽度约 2200 px，公众号正文宽度足够；要印刷再往上加。
"""
from __future__ import annotations

import argparse
import http.server
import os
import re
import socketserver
import subprocess
import sys
import threading
import time
import urllib.parse

EXPORTER = r"""
<script>
(function(){
  function faceCss(){
    var out='';
    document.querySelectorAll('style').forEach(function(s){
      (s.textContent.match(/@font-face\{[^}]*\}/g)||[]).forEach(function(f){out+=f;});
    });
    return out;
  }
  function post(name, blob){
    return fetch('/save?name='+encodeURIComponent(name),{method:'POST',body:blob});
  }
  function svgText(svg, bg){
    var vb=(svg.getAttribute('viewBox')||'0 0 1000 1000').split(/\s+/).map(Number);
    var w=vb[2], h=vb[3];
    var c=svg.cloneNode(true);
    c.setAttribute('xmlns','http://www.w3.org/2000/svg');
    c.setAttribute('width',w); c.setAttribute('height',h);
    var st=document.createElementNS('http://www.w3.org/2000/svg','style');
    st.textContent=faceCss();
    c.insertBefore(st, c.firstChild);
    var r=document.createElementNS('http://www.w3.org/2000/svg','rect');
    r.setAttribute('x',vb[0]); r.setAttribute('y',vb[1]);
    r.setAttribute('width',w); r.setAttribute('height',h); r.setAttribute('fill',bg);
    c.insertBefore(r, st.nextSibling);
    return {text:new XMLSerializer().serializeToString(c), w:w, h:h};
  }
  function raster(txt, w, h, scale){
    return new Promise(function(res, rej){
      var img=new Image();
      img.onload=function(){
        var cv=document.createElement('canvas');
        cv.width=Math.round(w*scale); cv.height=Math.round(h*scale);
        var g=cv.getContext('2d');
        g.setTransform(scale,0,0,scale,0,0);
        g.drawImage(img,0,0);
        cv.toBlob(function(b){b?res(b):rej(new Error('toBlob 失败'));},'image/png');
      };
      img.onerror=function(){rej(new Error('SVG 载入失败'));};
      img.src='data:image/svg+xml;base64,'+btoa(unescape(encodeURIComponent(txt)));
    });
  }

  /* ---- 几何与对比度自检（借鉴 diagram-design 的 verify-geometry 思路）---- */
  function lum(c){
    var m=/rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(c)||[];
    var v=[+m[1],+m[2],+m[3]].map(function(x){x/=255;return x<=0.04045?x/12.92:Math.pow((x+0.055)/1.055,2.4);});
    return 0.2126*v[0]+0.7152*v[1]+0.0722*v[2];
  }
  function ratio(a,b){var x=lum(a),y=lum(b);var hi=Math.max(x,y),lo=Math.min(x,y);return (hi+0.05)/(lo+0.05);}
  function toRGB(c){var d=document.createElement('div');d.style.color=c;document.body.appendChild(d);
    var v=getComputedStyle(d).color;d.remove();return v;}
  function inside(a,b,pad){pad=pad||0.5;
    return a.x>=b.x-pad&&a.y>=b.y-pad&&a.x+a.width<=b.x+b.width+pad&&a.y+a.height<=b.y+b.height+pad;}
  function hit(a,b){return !(a.x+a.width<=b.x||b.x+b.width<=a.x||a.y+a.height<=b.y||b.y+b.height<=a.y);}
  function lint(svg,id){
    var out=[];
    // 坐标一律折算回 SVG 自己的用户单位：屏幕坐标受 CSS 尺寸影响（SVG 没被给尺寸时
    // getBoundingClientRect() 会是 0×0，画布判据直接失效），而用户单位就是代码里写的那套数，
    // 报错时能直接对上源码。getScreenCTM 含全部祖先 transform，getBBox 不含。
    var ctm=svg.getScreenCTM();
    if(!ctm){return [id+'：拿不到 CTM，图未渲染'];}
    var inv=ctm.inverse();
    function toUser(r){
      var p=svg.createSVGPoint();
      p.x=r.left; p.y=r.top;  var a=p.matrixTransform(inv);
      p.x=r.right; p.y=r.bottom; var b=p.matrixTransform(inv);
      return {x:a.x,y:a.y,width:b.x-a.x,height:b.y-a.y};
    }
    var vb=(svg.getAttribute('viewBox')||'').split(/[\s,]+/).map(Number);
    var canvas=(vb.length===4&&vb[2])?{x:vb[0],y:vb[1],width:vb[2],height:vb[3]}
                                     :toUser(svg.getBoundingClientRect());
    var kids=[].slice.call(svg.querySelectorAll('g,text'));
    var paper=toRGB(getComputedStyle(document.documentElement).getPropertyValue('--paper').trim()||'#fff');
    var shapes=[],texts=[];
    kids.forEach(function(el,i){
      var bb; try{bb=toUser(el.getBoundingClientRect());}catch(e){return;}
      if(!bb||!bb.width||!bb.height)return;
      if(el.tagName==='text'){texts.push({el:el,bb:bb,i:i,t:el.textContent});}
      else{
        var pa=el.querySelector('path[fill]:not([fill="none"]),path[fill-rule]');
        var f=pa?pa.getAttribute('fill'):null;
        shapes.push({el:el,bb:bb,i:i,fill:(f&&f!=='none')?f:null});
      }
    });
    texts.forEach(function(t){
      if(!inside(t.bb,canvas,1)) out.push('溢出画布：「'+t.t.slice(0,18)+'」'+
        '（约在 '+Math.round(t.bb.x)+','+Math.round(t.bb.y)+'）');
      var owner=null;
      shapes.forEach(function(s){
        if(!s.fill)return;
        var cx=t.bb.x+t.bb.width/2, cy=t.bb.y+t.bb.height/2;
        if(cx>=s.bb.x&&cx<=s.bb.x+s.bb.width&&cy>=s.bb.y&&cy<=s.bb.y+s.bb.height){
          if(!owner||s.bb.width*s.bb.height<owner.bb.width*owner.bb.height) owner=s;
        }
      });
      if(owner&&!inside(t.bb,owner.bb,2)) out.push('文字戳出所属方框：「'+t.t.slice(0,18)+'」'+
        '（框约在 '+Math.round(owner.bb.x)+','+Math.round(owner.bb.y)+'）');
      var bg=owner?toRGB(owner.fill):paper;
      var fg=toRGB(t.el.getAttribute('fill')||'#000');
      var size=parseFloat(t.el.getAttribute('font-size')||'12');
      var need=size>=18?3:4.5, r=ratio(fg,bg);
      if(r<need) out.push('对比度不足 '+r.toFixed(2)+':1（需 '+need+'）：「'+t.t.slice(0,18)+'」');
    });
    for(var a=0;a<texts.length;a++)for(var b=a+1;b<texts.length;b++){
      if(hit(texts[a].bb,texts[b].bb))
        out.push('文字相互重叠：「'+texts[a].t.slice(0,12)+'」×「'+texts[b].t.slice(0,12)+'」');
    }
    return out.map(function(m){return id+'：'+m;});
  }

  async function run(){
    await document.fonts.ready;
    await new Promise(function(r){setTimeout(r,400);});
    var cs=getComputedStyle(document.documentElement);
    var bg=(cs.getPropertyValue('--paper')||cs.getPropertyValue('--card')).trim()
           ||getComputedStyle(document.body).backgroundColor||'#FFFFFF';
    var log=[];
    var list=[].slice.call(document.querySelectorAll('svg[id]'));
    for(var i=0;i<list.length;i++){
      var svg=list[i], id=svg.id;
      try{
        var o=svgText(svg,bg);
        if(__WITHSVG__){ await post(id+'.svg', new Blob([o.text],{type:'image/svg+xml'})); }
        var png=await raster(o.text,o.w,o.h,__SCALE__);
        await post(id+'.png', png);
        var issues=__LINT__?lint(svg,id):[];
        log.push(id+' ok '+o.w+'x'+o.h+(issues.length?('  ⚠ '+issues.length+' 处'):'  ✓ 自检通过'));
        issues.forEach(function(m){log.push('    '+m);});
      }catch(e){ log.push(id+' FAIL '+e.message); }
    }
    await fetch('/done',{method:'POST',body:log.join('\n')});
    document.body.innerHTML='<pre style="font:14px monospace;padding:24px">'+log.join('\n')+'\n\n导出完成，可以关掉这个标签页。</pre>';
  }
  if(document.readyState==='complete'){run();}else{window.addEventListener('load',run);}
})();
</script>
"""



# ── 自检器的对抗测试（借 diagram-design ADR 0005：检查器必须自带正反两极的用例）──
# 只有「坏图被报出来」不够，还要保证「好图不被误报」，否则调松阈值就能骗过自己。
SELFTEST_PAGE = """
<title>lint selftest</title>
<style>:root{--paper:#F7F2E4}body{margin:0;background:#F7F2E4}svg{display:block}</style>
<svg id="bad" viewBox="0 0 460 220">
  <g><path d="M20 20 H180 V80 H20 Z" fill="#FFE3C7" stroke="#E8590C"/></g>
  <text x="100" y="55" font-size="20" text-anchor="middle" fill="#A03C08">这一行明显比方框宽得多</text>
  <g><path d="M240 20 H440 V80 H240 Z" fill="#FFE3C7" stroke="#E8590C"/></g>
  <text x="340" y="55" font-size="13" text-anchor="middle" fill="#E8590C">对比度不够</text>
  <text x="100" y="140" font-size="14" text-anchor="middle" fill="#1E1E1E">重叠甲</text>
  <text x="100" y="140" font-size="14" text-anchor="middle" fill="#1E1E1E">重叠乙</text>
  <text x="300" y="205" font-size="14" text-anchor="start" fill="#1E1E1E">这一行会伸出画布右边缘之外</text>
</svg>
<svg id="good" viewBox="0 0 460 220">
  <g><path d="M20 20 H180 V80 H20 Z" fill="#FFE3C7" stroke="#E8590C"/></g>
  <text x="100" y="55" font-size="13" text-anchor="middle" fill="#A03C08">装得下</text>
  <g><path d="M240 20 H440 V80 H240 Z" fill="#FFE3C7" stroke="#E8590C"/></g>
  <text x="340" y="55" font-size="13" text-anchor="middle" fill="#A03C08">对比度够</text>
  <text x="100" y="140" font-size="14" text-anchor="middle" fill="#1E1E1E">互不重叠</text>
  <text x="300" y="140" font-size="14" text-anchor="middle" fill="#1E1E1E">也在画布内</text>
</svg>
"""

SELFTEST_EXPECT = ["戳出所属方框", "对比度不足", "相互重叠", "溢出画布"]


def check_selftest(log: str) -> int:
    bad = [l for l in log.split("\n") if l.strip().startswith("bad：")]
    good = [l for l in log.split("\n") if l.strip().startswith("good：")]
    ok = True
    for kind in SELFTEST_EXPECT:
        hit = any(kind in l for l in bad)
        print(f"  {'✅' if hit else '❌'} 坏图应报出「{kind}」")
        ok &= hit
    print(f"  {'✅' if not good else '❌'} 好图不应有任何告警" + (f"（实际 {len(good)} 条）" if good else ""))
    ok &= not good
    for l in good:
        print(f"     误报：{l.strip()}")
    return 0 if ok else 1


def build(page_path: str, scale: float, with_svg: bool, lint: bool) -> bytes:
    html = open(page_path, encoding="utf-8").read()
    head = ('<!doctype html><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">')
    js = EXPORTER.replace("__SCALE__", str(scale)).replace("__WITHSVG__", "true" if with_svg else "false").replace("__LINT__", "true" if lint else "false")
    return (head + html + js).encode("utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("page", nargs="?", help="配图页 .html（--selftest 时可省略）")
    ap.add_argument("--selftest", action="store_true", help="用内置正反用例验一遍自检器本身")
    ap.add_argument("--out", help="输出目录（--selftest 时可省略）")
    ap.add_argument("--scale", type=float, default=2.0, help="PNG 倍率，默认 2")
    ap.add_argument("--port", type=int, default=8732)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--no-lint", action="store_true", help="跳过几何与对比度自检")
    ap.add_argument("--svg", action="store_true", help="同时导出矢量 .svg（默认只出 PNG，成品目录只放最终要用的图）")
    ap.add_argument("--no-open", action="store_true", help="不自动开浏览器，自己去访问打印出来的地址")
    a = ap.parse_args()

    if a.selftest:
        import tempfile
        a.out = a.out or tempfile.mkdtemp(prefix="lint-selftest-")
        os.makedirs(a.out, exist_ok=True)
        head = ('<!doctype html><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">')
        js = EXPORTER.replace("__SCALE__", "1").replace("__WITHSVG__", "false").replace("__LINT__", "true")
        doc = (head + SELFTEST_PAGE + js).encode("utf-8")
    else:
        if not a.page or not os.path.exists(a.page):
            print(f"[ERROR] 找不到页面：{a.page}", file=sys.stderr)
            return 1
        if not a.out:
            print("[ERROR] 缺 --out", file=sys.stderr)
            return 1
        os.makedirs(a.out, exist_ok=True)
        doc = build(a.page, a.scale, a.svg, not a.no_lint)
    state = {"done": False, "log": "", "files": []}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):  # 不刷屏
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(doc)))
            self.end_headers()
            self.wfile.write(doc)

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(n)
            path = urllib.parse.urlparse(self.path)
            if path.path == "/save":
                name = urllib.parse.parse_qs(path.query).get("name", ["x.bin"])[0]
                name = os.path.basename(name)
                if not re.fullmatch(r"[\w.-]+\.(svg|png)", name):
                    self.send_response(400); self.end_headers(); return
                with open(os.path.join(a.out, name), "wb") as f:
                    f.write(body)
                state["files"].append((name, len(body)))
            elif path.path == "/done":
                state["log"] = body.decode("utf-8", "replace")
                state["done"] = True
            self.send_response(204)
            self.end_headers()

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", a.port), H) as srv:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{a.port}/"
        print(f"导出服务已起：{url}")
        if a.no_open:
            print("请用浏览器打开上面这个地址，页面会自己导出。")
        else:
            subprocess.run(["open", url], check=False)
        t0 = time.time()
        while not state["done"] and time.time() - t0 < a.timeout:
            time.sleep(0.25)
        srv.shutdown()

    if not state["done"]:
        print(f"[ERROR] {a.timeout} 秒内没等到浏览器回传，导出未完成。", file=sys.stderr)
        return 1
    if a.selftest:
        print("自检器对抗测试：")
        return check_selftest(state["log"])
    for name, size in sorted(state["files"]):
        print(f"  ✔ {os.path.join(a.out, name)}　{size // 1024} KB")
    print(state["log"])
    bad = ("FAIL" in state["log"]) or ("⚠" in state["log"])
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
