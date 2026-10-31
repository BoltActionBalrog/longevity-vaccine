// Minimal Frida-API shim to surface load-time exceptions in hook_dl_scale_proto.js
function P(v){ this.v = (typeof v==='number')?v:0; }
P.prototype.add=function(n){return new P(this.v+(n&&n.v!==undefined?n.v:n));};
P.prototype.sub=function(n){return new P(this.v-(n&&n.v!==undefined?n.v:n));};
P.prototype.readS32=function(){return 0;}; P.prototype.readU32=function(){return 0;};
P.prototype.readPointer=function(){return new P(0);};
P.prototype.readByteArray=function(n){return new ArrayBuffer(Math.max(0,n|0));};
P.prototype.readCString=function(){return "";};
P.prototype.writeS32=function(){return this;}; P.prototype.writeU32=function(){return this;};
P.prototype.writePointer=function(){return this;}; P.prototype.writeByteArray=function(){return this;};
P.prototype.toInt32=function(){return this.v|0;}; P.prototype.toUInt32=function(){return this.v>>>0;};
P.prototype.equals=function(o){return o&&o.v===this.v;}; P.prototype.isNull=function(){return this.v===0;};
P.prototype.toString=function(){return "0x"+(this.v>>>0).toString(16);};
globalThis.ptr=v=>new P(typeof v==='string'?parseInt(v,16):v);
globalThis.NULL=new P(0);
globalThis.VA=a=>new P(0x400000+((a&&a.v!==undefined?a.v:a)-0x400000));
globalThis.log=(...a)=>console.log("[log]",...a);
globalThis.requireBase=()=>true;
globalThis.installAVHandler=()=>{};
globalThis.u32=v=>v>>>0;
globalThis.arg=(esp,n)=>new P(0); globalThis.argS=()=>0; globalThis.bufWH=()=>({w:0,h:0});
globalThis.Memory={alloc:n=>new P(0x5000000+Math.floor(Math.random()*0x100000)),patchCode:(p,l,cb)=>{const w=new P(p.v);w.writeByteArray=()=>w;w.writeU32=()=>w;w.writeS32=()=>w;cb(w);}};
globalThis.Interceptor={attach:(a,c)=>({detach(){}}),replace:()=>{},revert:()=>{}};
globalThis.Process={pageSize:4096,arch:"ia32",platform:"windows",
  getModuleByName:n=>({base:new P(0x400000),getExportByName:e=>new P(0x77000000)}),
  findModuleByName:n=>({base:new P(0x400000)}),
  enumerateModules:()=>[],enumerateThreads:()=>[{id:1}],getCurrentThreadId:()=>1,
  setExceptionHandler:()=>{}};
globalThis.Module={findBaseAddress:()=>new P(0x400000)};
globalThis.NativeFunction=function(){ const f=function(){return 0;}; return f; };
globalThis.File=function(){return {write(){},flush(){},close(){}};};
globalThis.hexdump=()=>"";
try {
  require(process.argv[2]||'D:/SmacxUi/work/scripts/scaling_laws.js');
} catch(e) { console.log("scaling_laws load note:", e.message); }
try {
  require('D:/SmacxUi/work/scripts/hook_dl_scale_proto.js');
  console.log("=== LOAD COMPLETED WITHOUT THROW ===");
} catch(e) {
  console.log("=== LOAD THREW ===");
  console.log(e.stack || e);
}
