package com.flashdrop.app;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;

/** 线协议常量与读写原语，与桌面端 flashdrop/protocol.py 保持一致。 */
public final class Proto {
    private Proto() {}

    public static final byte[] MAGIC = {'F', 'D', '0', '1'};
    public static final String TAG = "flashdrop";
    public static final int VERSION = 1;
    public static final int UDP_PORT = 47831;
    public static final int TCP_PORT = 47832;
    public static final int CHUNK = 64 * 1024;
    public static final int DISCOVERY_INTERVAL_MS = 2000;
    public static final int PEER_TTL_MS = 7000;
    public static final int SOCKET_TIMEOUT_MS = 120000;
    public static final int MAX_HEADER = 4 * 1024 * 1024;
    public static final int MAX_TEXT = 1024 * 1024;

    public static byte[] u32(long n) {
        return new byte[]{
                (byte) ((n >>> 24) & 0xff), (byte) ((n >>> 16) & 0xff),
                (byte) ((n >>> 8) & 0xff), (byte) (n & 0xff)
        };
    }

    public static long fromU32(byte[] b, int off) {
        return ((long) (b[off] & 0xff) << 24) | ((long) (b[off + 1] & 0xff) << 16)
                | ((long) (b[off + 2] & 0xff) << 8) | (b[off + 3] & 0xffL);
    }

    public static byte[] readExact(InputStream in, int n) throws IOException {
        byte[] buf = new byte[n];
        int off = 0;
        while (off < n) {
            int r = in.read(buf, off, n - off);
            if (r < 0) throw new IOException("对端提前断开了连接");
            off += r;
        }
        return buf;
    }

    public static String readString(InputStream in, int n) throws IOException {
        return new String(readExact(in, n), StandardCharsets.UTF_8);
    }

    public static byte[] utf8(String s) {
        return s.getBytes(StandardCharsets.UTF_8);
    }

    public static String safeRel(String rel) throws IOException {
        if (rel == null || rel.isEmpty()) throw new IOException("空的相对路径");
        rel = rel.replace('\\', '/');
        String[] parts = rel.split("/", -1);
        if (rel.startsWith("/") || parts[0].contains(":") || rel.contains("\u0000"))
            throw new IOException("非法的相对路径: " + rel);
        for (String p : parts) {
            if (p.isEmpty() || p.equals(".") || p.equals(".."))
                throw new IOException("非法的相对路径: " + rel);
        }
        return rel;
    }

    public static byte[] concat(byte[] a, byte[] b) {
        ByteArrayOutputStream out = new ByteArrayOutputStream(a.length + b.length);
        out.write(a, 0, a.length);
        out.write(b, 0, b.length);
        return out.toByteArray();
    }
}
