package com.flashdrop.app;

import android.content.ContentResolver;
import android.content.ContentUris;
import android.content.ContentValues;
import android.content.Context;
import android.content.SharedPreferences;
import android.database.Cursor;
import android.media.MediaScannerConnection;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.provider.MediaStore;
import android.util.Log;
import android.webkit.MimeTypeMap;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.InterfaceAddress;
import java.net.NetworkInterface;
import java.net.ServerSocket;
import java.net.Socket;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.zip.CRC32;

/** 发现 + 投递引擎单例，由 RecvService 持有生命周期。 */
public final class Hub {
    private static final String LOGTAG = "FlashDrop";
    private static final String PREF = "flashdrop";
    private static final Hub I = new Hub();
    private final Handler main = new Handler(Looper.getMainLooper());
    private final Object peerLock = new Object();
    private final LinkedHashMap<String, Peer> peers = new LinkedHashMap<>();
    private ExecutorService senders = Executors.newSingleThreadExecutor();

    private Context app;
    private String myId = "";
    private String myName = "";
    private volatile boolean running = false;
    private volatile Listener listener;
    private DatagramSocket udp;
    private ServerSocket tcp;

    private Hub() {}

    public static Hub get() { return I; }

    public interface Listener {
        void onPeers(List<Peer> peers);
        void onLog(String msg);
        void onProgress(long done, long total);
        void onText(String text, String from);
        void onFiles(int count, String from);
    }

    public interface Result { void done(boolean ok, String msg); }

    public static final class Peer {
        public final String id, name, os, ip;
        public final int tcp;
        public final boolean manual;
        public long lastSeen = System.currentTimeMillis();

        Peer(String id, String name, String os, String ip, int tcp, boolean manual) {
            this.id = id; this.name = name; this.os = os;
            this.ip = ip; this.tcp = tcp; this.manual = manual;
        }
        public String label() { return manual ? name + " (" + ip + ")" : name; }
    }

    /** 发送侧的一个条目：rel 为投递内相对路径，dir 条目没有 uri。 */
    public static final class Item {
        public final String rel;
        public final long size;
        public final boolean dir;
        public final Uri uri;
        public Item(String rel, long size, boolean dir, Uri uri) {
            this.rel = rel; this.size = size; this.dir = dir; this.uri = uri;
        }
    }

    // ---------------------------------------------------------------- 生命周期
    public synchronized void start(Context ctx) {
        if (running) { firePeers(); return; }
        this.app = ctx.getApplicationContext();
        SharedPreferences sp = app.getSharedPreferences(PREF, Context.MODE_PRIVATE);
        myId = sp.getString("id", "");
        if (myId.isEmpty()) {
            myId = UUID.randomUUID().toString();
            sp.edit().putString("id", myId).apply();
        }
        myName = "手机-" + Build.MODEL;
        if (senders.isShutdown()) senders = Executors.newSingleThreadExecutor();
        running = true;
        new Thread(this::udpRecvLoop, "fd-udp-recv").start();
        new Thread(this::announceLoop, "fd-udp-announce").start();
        new Thread(this::sweepLoop, "fd-sweep").start();
        new Thread(this::tcpAcceptLoop, "fd-tcp-accept").start();
        log("已启动 · 本机 " + myName + " · 收件目录 Download/FlashDrop");
        log("等待对端…（两端都要打开 FlashDrop）");
    }

    public synchronized void stop() {
        running = false;
        try { if (udp != null) { udp.close(); udp = null; } } catch (Exception ignored) {}
        try { if (tcp != null) { tcp.close(); tcp = null; } } catch (Exception ignored) {}
        synchronized (peerLock) { peers.clear(); }
        senders.shutdownNow();
        firePeers();
        log("已停止接收");
    }

    public void setListener(Listener l) {
        listener = l;
        firePeers();
    }

    public boolean isRunning() { return running; }
    public String myName() { return myName; }

    public SharedPreferences prefs() {
        return app.getSharedPreferences(PREF, Context.MODE_PRIVATE);
    }

    private void log(String s) {
        Log.d(LOGTAG, s);
        Listener l = listener;
        if (l != null) main.post(() -> l.onLog(s));
    }

    private void firePeers() {
        List<Peer> copy;
        synchronized (peerLock) { copy = new ArrayList<>(peers.values()); }
        Listener l = listener;
        if (l != null) main.post(() -> l.onPeers(copy));
    }

    // ---------------------------------------------------------------- 发现
    private JSONObject hello(boolean bye, boolean reply) {
        try {
            JSONObject o = new JSONObject();
            o.put("p", Proto.TAG).put("v", Proto.VERSION)
                    .put("id", myId).put("name", myName)
                    .put("os", "android").put("tcp", Proto.TCP_PORT)
                    .put("bye", bye);
            if (reply) o.put("r", true);
            return o;
        } catch (Exception e) { return new JSONObject(); }
    }

    private List<String> broadcastTargets() {
        Set<String> out = new LinkedHashSet<>();
        out.add("255.255.255.255");
        try {
            for (NetworkInterface ni : Collections.list(NetworkInterface.getNetworkInterfaces())) {
                for (InterfaceAddress ia : ni.getInterfaceAddresses()) {
                    InetAddress a = ia.getAddress();
                    if (a instanceof java.net.Inet4Address && !a.isLoopbackAddress()) {
                        byte[] b = a.getAddress();
                        short len = ia.getNetworkPrefixLength();
                        int mask = len <= 0 ? 0xFFFFFF00 : (int) (0xFFFFFFFFL << (32 - len));
                        int ip = toInt(b), bc = (ip & mask) | (~mask);
                        out.add(fromInt(bc));
                    }
                }
            }
        } catch (Exception ignored) {}
        return new ArrayList<>(out);
    }

    /** 本机局域网 IPv4，显示在界面上供电脑端「手填 IP」使用。 */
    public static String localIp() {
        String fallback = "";
        try {
            for (NetworkInterface ni : Collections.list(NetworkInterface.getNetworkInterfaces())) {
                for (java.util.Enumeration<InetAddress> es = ni.getInetAddresses(); es.hasMoreElements(); ) {
                    InetAddress a = es.nextElement();
                    if (a instanceof java.net.Inet4Address && !a.isLoopbackAddress()
                            && !a.isLinkLocalAddress()) {
                        String ip = a.getHostAddress();
                        if (ip == null) continue;
                        if (fallback.isEmpty()) fallback = ip;
                        if (ip.startsWith("192.168.") || ip.startsWith("10.")) return ip;
                    }
                }
            }
        } catch (Exception ignored) {}
        return fallback.isEmpty() ? "未知" : fallback;
    }

    private static int toInt(byte[] b) {
        return ((b[0] & 0xff) << 24) | ((b[1] & 0xff) << 16) | ((b[2] & 0xff) << 8) | (b[3] & 0xff);
    }

    private static String fromInt(int v) {
        return ((v >>> 24) & 0xff) + "." + ((v >>> 16) & 0xff) + "."
                + ((v >>> 8) & 0xff) + "." + (v & 0xff);
    }

    private void sendHello(JSONObject payload, List<String> targets) {
        DatagramSocket s = udp;
        if (s == null) return;
        byte[] data = Proto.utf8(payload.toString());
        for (String t : targets) {
            try {
                s.send(new DatagramPacket(data, data.length,
                        InetAddress.getByName(t), Proto.UDP_PORT));
            } catch (Exception e) {
                Log.w(LOGTAG, "broadcast -> " + t + " failed: " + e);
            }
        }
    }

    private void announceLoop() {
        while (running) {
            sendHello(hello(false, false), broadcastTargets());
            try { Thread.sleep(Proto.DISCOVERY_INTERVAL_MS); } catch (InterruptedException e) { return; }
        }
    }

    private void udpRecvLoop() {
        try {
            DatagramSocket s = new DatagramSocket(null);
            s.setReuseAddress(true);
            s.setBroadcast(true);
            s.bind(new InetSocketAddress(Proto.UDP_PORT));
            s.setSoTimeout(1000);
            udp = s;
            byte[] buf = new byte[4096];
            while (running) {
                try {
                    DatagramPacket p = new DatagramPacket(buf, buf.length);
                    s.receive(p);
                    JSONObject o = new JSONObject(new String(p.getData(), 0, p.getLength(),
                            java.nio.charset.StandardCharsets.UTF_8));
                    if (!Proto.TAG.equals(o.optString("p")) || o.optInt("v") != Proto.VERSION) continue;
                    String id = o.optString("id");
                    if (id.isEmpty() || id.equals(myId)) continue;
                    String ip = p.getAddress().getHostAddress();
                    synchronized (peerLock) {
                        if (o.optBoolean("bye")) {
                            peers.remove(id);
                        } else {
                            peers.put(id, new Peer(id, o.optString("name", ip),
                                    o.optString("os", ""), ip,
                                    o.optInt("tcp", Proto.TCP_PORT), false));
                        }
                    }
                    // 单播回一个 hello，让对方即使收不到广播也能认识我们
                    if (!o.optBoolean("r")) {
                        sendHello(hello(false, true), Collections.singletonList(ip));
                    }
                    firePeers();
                } catch (java.net.SocketTimeoutException ignored) {
                } catch (Exception e) {
                    Log.w(LOGTAG, "udp recv: " + e);
                }
            }
        } catch (Exception e) {
            log("自动发现启动失败：" + e.getMessage() + "（可用「手填 IP」）");
        }
    }

    private void sweepLoop() {
        while (running) {
            try { Thread.sleep(1000); } catch (InterruptedException e) { return; }
            long now = System.currentTimeMillis();
            boolean changed = false;
            synchronized (peerLock) {
                java.util.Iterator<Map.Entry<String, Peer>> it = peers.entrySet().iterator();
                while (it.hasNext()) {
                    Peer p = it.next().getValue();
                    if (!p.manual && now - p.lastSeen > Proto.PEER_TTL_MS) {
                        it.remove(); changed = true;
                    }
                }
            }
            if (changed) firePeers();
        }
    }

    public List<Peer> peers() {
        synchronized (peerLock) {
            List<Peer> r = new ArrayList<>(peers.values());
            Collections.sort(r, (a, b) -> a.name.compareTo(b.name));
            return r;
        }
    }

    public void ping(String ip) {
        ip = ip.trim();
        if (ip.isEmpty()) return;
        synchronized (peerLock) {
            peers.put("manual:" + ip, new Peer("manual:" + ip, ip, "", ip,
                    Proto.TCP_PORT, true));
        }
        sendHello(hello(false, true), Collections.singletonList(ip));
        log("已手动添加对端 " + ip);
        firePeers();
    }

    // ---------------------------------------------------------------- 接收
    private void tcpAcceptLoop() {
        try {
            ServerSocket srv = new ServerSocket();
            srv.setReuseAddress(true);
            srv.bind(new InetSocketAddress(Proto.TCP_PORT), 8);
            srv.setSoTimeout(1000);
            tcp = srv;
            while (running) {
                try {
                    final Socket c = srv.accept();
                    new Thread(() -> handleConnection(c), "fd-tcp-recv").start();
                } catch (java.net.SocketTimeoutException ignored) {
                } catch (Exception e) {
                    if (running) Log.w(LOGTAG, "accept: " + e);
                }
            }
        } catch (Exception e) {
            log("TCP 接收启动失败：" + e.getMessage());
        }
    }

    private void handleConnection(Socket sock) {
        boolean ok = false;
        String msg = "";
        try {
            sock.setSoTimeout(Proto.SOCKET_TIMEOUT_MS);
            InputStream in = sock.getInputStream();
            if (!Arrays.equals(Proto.readExact(in, 4), Proto.MAGIC))
                throw new IOException("协议标识不匹配");
            long hlen = Proto.fromU32(Proto.readExact(in, 4), 0);
            if (hlen > Proto.MAX_HEADER) throw new IOException("投递头过大");
            JSONObject h = new JSONObject(Proto.readString(in, (int) hlen));
            if (h.optInt("v") != Proto.VERSION) throw new IOException("协议版本不匹配");
            String from = h.optString("from", "对端");
            String kind = h.optString("kind");

            if ("text".equals(kind)) {
                String text = h.optString("text", "");
                Listener l = listener;
                if (l != null) main.post(() -> l.onText(text, from));
                ok = true;
                msg = "文字已送达";
                log("收到来自 " + from + " 的文字（" + text.length() + " 字）");
            } else if ("files".equals(kind)) {
                int n = receiveFiles(in, h.getJSONArray("entries"));
                Listener l = listener;
                if (l != null) main.post(() -> l.onFiles(n, from));
                ok = true;
                msg = "已接收 " + n + " 项";
                log("收到来自 " + from + " 的 " + n + " 项文件 → Download/FlashDrop");
            } else {
                throw new IOException("未知的投递类型");
            }
        } catch (Exception e) {
            msg = e.getMessage() == null ? e.toString() : e.getMessage();
            log("接收失败：" + msg);
        } finally {
            try {
                OutputStream out = sock.getOutputStream();
                byte[] m = Proto.utf8(msg);
                out.write(new byte[]{(byte) (ok ? 1 : 0)});
                out.write(Proto.u32(m.length));
                out.write(m);
                out.flush();
            } catch (Exception ignored) {}
            try { sock.close(); } catch (Exception ignored) {}
        }
    }

    private static final class Entry {
        String rel; long size; boolean dir; String relPath; String display;
    }

    private int receiveFiles(InputStream in, JSONArray arr) throws Exception {
        List<Entry> list = new ArrayList<>();
        LinkedHashSet<String> tops = new LinkedHashSet<>();
        for (int i = 0; i < arr.length(); i++) {
            JSONObject o = arr.getJSONObject(i);
            Entry e = new Entry();
            e.rel = Proto.safeRel(o.optString("rel"));
            e.size = o.optLong("size");
            e.dir = o.optBoolean("dir");
            list.add(e);
            tops.add(e.rel.split("/")[0]);
        }
        Map<String, String> roots = new LinkedHashMap<>();
        for (String t : tops) roots.put(t, uniqueRoot(t));

        for (Entry e : list) {
            String[] parts = e.rel.split("/");
            if (parts.length == 1) {
                e.relPath = "Download/FlashDrop/";
                e.display = uniqueName(parts[0], e.relPath);
            } else {
                StringBuilder mid = new StringBuilder();
                for (int i = 1; i < parts.length - 1; i++) mid.append(parts[i]).append('/');
                e.relPath = "Download/FlashDrop/" + roots.get(parts[0]) + "/" + mid;
                e.display = parts[parts.length - 1];
            }
        }

        ContentResolver cr = app.getContentResolver();
        Uri collection = MediaStore.Downloads.EXTERNAL_CONTENT_URI;
        int count = 0;
        for (Entry e : list) {
            if (e.dir) {
                Proto.readExact(in, 4);   // MediaStore 无法表示空目录，跳过
                count++;
                continue;
            }
            ContentValues cv = new ContentValues();
            cv.put(MediaStore.MediaColumns.DISPLAY_NAME, e.display);
            cv.put(MediaStore.MediaColumns.MIME_TYPE, mime(e.display));
            cv.put(MediaStore.MediaColumns.RELATIVE_PATH, e.relPath);
            cv.put(MediaStore.MediaColumns.IS_PENDING, 1);
            Uri row = cr.insert(collection, cv);
            if (row == null) throw new IOException("无法创建文件：" + e.display);
            OutputStream os = cr.openOutputStream(row);
            if (os == null) throw new IOException("无法写入文件：" + e.display);
            CRC32 crc = new CRC32();
            long left = e.size;
            byte[] buf = new byte[Proto.CHUNK];
            boolean verified = false;
            try {
                while (left > 0) {
                    int want = (int) Math.min(buf.length, left);
                    int r = in.read(buf, 0, want);
                    if (r < 0) throw new IOException("文件数据不完整");
                    os.write(buf, 0, r);
                    crc.update(buf, 0, r);
                    left -= r;
                }
                long expected = Proto.fromU32(Proto.readExact(in, 4), 0);
                if (crc.getValue() != expected)
                    throw new IOException("校验失败，已丢弃：" + e.rel);
                os.flush();
                verified = true;
            } finally {
                try { os.close(); } catch (Exception ignored) {}
                if (!verified) cr.delete(row, null, null);
            }
            cv.clear();
            cv.put(MediaStore.MediaColumns.IS_PENDING, 0);
            cr.update(row, cv, null, null);
            count++;
        }
        return count;
    }

    private String uniqueRoot(String top) {
        Uri collection = MediaStore.Downloads.EXTERNAL_CONTENT_URI;
        String candidate = top;
        for (int i = 2; ; i++) {
            String prefix = "Download/FlashDrop/" + candidate + "/";
            Cursor c = app.getContentResolver().query(collection,
                    new String[]{MediaStore.MediaColumns._ID},
                    MediaStore.MediaColumns.RELATIVE_PATH + " LIKE ?",
                    new String[]{prefix + "%"}, null);
            boolean exists = c != null && c.getCount() > 0;
            if (c != null) c.close();
            if (!exists) return candidate;
            candidate = top + " (" + i + ")";
        }
    }

    private String uniqueName(String name, String relPath) {
        String candidate = name;
        for (int i = 2; ; i++) {
            Cursor c = app.getContentResolver().query(MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                    new String[]{MediaStore.MediaColumns._ID},
                    MediaStore.MediaColumns.RELATIVE_PATH + "=? AND "
                            + MediaStore.MediaColumns.DISPLAY_NAME + "=?",
                    new String[]{relPath, candidate}, null);
            boolean exists = c != null && c.getCount() > 0;
            if (c != null) c.close();
            if (!exists) return candidate;
            int dot = name.lastIndexOf('.');
            candidate = (dot > 0 ? name.substring(0, dot) + " (" + i + ")" + name.substring(dot)
                    : name + " (" + i + ")");
        }
    }

    private static String mime(String name) {
        int dot = name.lastIndexOf('.');
        if (dot >= 0) {
            String m = MimeTypeMap.getSingleton()
                    .getMimeTypeFromExtension(name.substring(dot + 1).toLowerCase());
            if (m != null) return m;
        }
        return "application/octet-stream";
    }

    /** 已接收的文件（来自 MediaStore 的 Download/FlashDrop）。 */
    public static final class Received {
        public final long id, size, date;
        public final String name, relPath, mime;
        public final Uri uri;
        Received(long id, String name, String relPath, String mime, long size, long date, Uri uri) {
            this.id = id; this.name = name; this.relPath = relPath;
            this.mime = mime; this.size = size; this.date = date; this.uri = uri;
        }
    }

    public List<Received> receivedFiles() {
        List<Received> out = new ArrayList<>();
        if (app == null) return out;
        Uri col = MediaStore.Downloads.EXTERNAL_CONTENT_URI;
        String[] proj = {
                MediaStore.MediaColumns._ID,
                MediaStore.MediaColumns.DISPLAY_NAME,
                MediaStore.MediaColumns.RELATIVE_PATH,
                MediaStore.MediaColumns.MIME_TYPE,
                MediaStore.MediaColumns.SIZE,
                MediaStore.MediaColumns.DATE_ADDED
        };
        Cursor c = null;
        try {
            c = app.getContentResolver().query(col, proj,
                    MediaStore.MediaColumns.RELATIVE_PATH + " LIKE ? AND "
                            + MediaStore.MediaColumns.IS_PENDING + "=0",
                    new String[]{"Download/FlashDrop/%"},
                    MediaStore.MediaColumns.DATE_ADDED + " DESC");
            if (c == null) return out;
            while (c.moveToNext()) {
                long id = c.getLong(0);
                out.add(new Received(id,
                        c.isNull(1) ? "文件" : c.getString(1),
                        c.isNull(2) ? "" : c.getString(2),
                        c.isNull(3) ? "application/octet-stream" : c.getString(3),
                        c.isNull(4) ? 0 : c.getLong(4),
                        c.isNull(5) ? 0 : c.getLong(5),
                        ContentUris.withAppendedId(col, id)));
            }
        } catch (Exception e) {
            Log.w(LOGTAG, "list received: " + e);
        } finally {
            if (c != null) c.close();
        }
        return out;
    }

    // ---------------------------------------------------------------- 发送
    public void sendText(String text, Peer p, Result cb) {
        if (Proto.utf8(text).length > Proto.MAX_TEXT) {
            postResult(cb, false, "文字超过 1MB 上限");
            return;
        }
        senders.execute(() -> {
            try {
                JSONObject h = new JSONObject();
                h.put("kind", "text").put("text", text);
                finish(cb, sendFrame(h, null, p));
            } catch (Exception e) { postResult(cb, false, e.toString()); }
        });
    }

    public void sendFiles(List<Item> items, Peer p, Result cb) {
        senders.execute(() -> {
            try {
                JSONArray arr = new JSONArray();
                long total = 0;
                for (Item it : items) {
                    JSONObject o = new JSONObject();
                    o.put("rel", it.rel).put("size", it.size).put("dir", it.dir);
                    arr.put(o);
                    total += it.size;
                }
                JSONObject h = new JSONObject();
                h.put("kind", "files").put("entries", arr).put("total", total);
                finish(cb, sendFrame(h, items, p));
            } catch (Exception e) { postResult(cb, false, e.toString()); }
        });
    }

    private void finish(Result cb, boolean ok) {
        postResult(cb, ok, ok ? "已送达" : (lastError.isEmpty() ? "发送失败" : lastError));
    }

    private void postResult(Result cb, boolean ok, String msg) {
        if (cb != null) main.post(() -> cb.done(ok, msg));
    }

    /** 返回是否成功；失败原因写入 lastError。 */
    private volatile String lastError = "";

    private boolean sendFrame(JSONObject header, List<Item> items, Peer p) {
        Socket s = new Socket();
        try {
            s.connect(new InetSocketAddress(p.ip, p.tcp), 8000);
            s.setSoTimeout(Proto.SOCKET_TIMEOUT_MS);
            header.put("v", Proto.VERSION).put("from", myName);
            byte[] hb = Proto.utf8(header.toString());
            OutputStream out = s.getOutputStream();
            out.write(Proto.MAGIC);
            out.write(Proto.u32(hb.length));
            out.write(hb);

            if (items != null) {
                long total = header.optLong("total");
                long done = 0;
                for (Item it : items) {
                    if (it.dir) { out.write(Proto.u32(0)); continue; }
                    InputStream in = app.getContentResolver().openInputStream(it.uri);
                    if (in == null) throw new IOException("打不开文件：" + it.rel);
                    CRC32 crc = new CRC32();
                    byte[] buf = new byte[Proto.CHUNK];
                    try {
                        int r;
                        while ((r = in.read(buf)) > 0) {
                            out.write(buf, 0, r);
                            crc.update(buf, 0, r);
                            done += r;
                            final long d = done, t = total;
                            Listener l = listener;
                            if (l != null) main.post(() -> l.onProgress(d, t));
                        }
                    } finally {
                        try { in.close(); } catch (Exception ignored) {}
                    }
                    out.write(Proto.u32(crc.getValue()));
                }
            }
            out.flush();
            InputStream in = s.getInputStream();
            int status = in.read();
            long mlen = Proto.fromU32(Proto.readExact(in, 4), 0);
            String msg = Proto.readString(in, (int) mlen);
            lastError = msg;
            return status == 1;
        } catch (Exception e) {
            lastError = e.getMessage() == null ? e.toString() : e.getMessage();
            log("发送失败：" + lastError);
            return false;
        } finally {
            try { s.close(); } catch (Exception ignored) {}
        }
    }

    /** 供 UI 取最近一次发送结果文本。 */
    public String lastError() { return lastError; }
}
