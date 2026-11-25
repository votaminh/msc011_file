// Replaces the JSON handed to the native ScriptSegment load function so that
// script_path points at the extracted SegmentJS directory.
var PATH = '/data/user/0/com.example.capcutedit/files/inner_resource/SegmentJS/SegmentJS';
var json = '{"forInitScript":true,"script_path":"' + PATH + '"}';
var buf = Memory.allocUtf8String(json);            // kept alive by this reference
var fake = Memory.alloc(32);                       // libc++ long std::string
fake.writeU64(uint64(((json.length + 16) & ~1) | 1));
fake.add(8).writeU64(uint64(json.length));
fake.add(16).writePointer(buf);

function str(p) {
  try {
    var b0 = p.readU8();
    if ((b0 & 1) === 0) { var n = b0 >> 1; return n ? p.add(1).readUtf8String(n) : ''; }
    var size = p.add(8).readU64().toNumber();
    return p.add(16).readPointer().readUtf8String(size);
  } catch (e) { return '<err>'; }
}

var done = false;
var t = setInterval(function () {
  if (done) return;
  var m = Process.findModuleByName('libcccreator.so');
  if (!m) return;
  done = true; clearInterval(t);
  Interceptor.attach(m.base.add(0xad8440), {
    onEnter: function (args) {
      console.log('SCRIPT-LOAD was ' + str(args[1]) + '  -> replaced');
      args[1] = fake;
    }
  });
  console.log('hooked, will inject script_path=' + PATH);
}, 20);
