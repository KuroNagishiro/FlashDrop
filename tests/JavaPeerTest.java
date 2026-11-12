/** 跨语言联调：复用 android/src 的 Proto.java，验证 Java 帧与 Python 帧逐字节一致。
 *  java -cp <out> JavaPeerTest <recv|recvtext|send|sendtext> <path-or-text>
 *  由 tests/cross_lang_test.py 驱动。
 */
import com.flashdrop.app.Proto;

import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.regex.*;
import java.util.zip.CRC32;

public class JavaPeerTest {
    public static void main(String[] args) throws Exception {
        String mode = args[0];
        switch (mode) {
            case "recv": recvFile(Paths.get(args[1])); break;
            case "recvtext": recvText(); break;
            case "send": sendFile(Paths.get(args[1])); break;
            case "sendtext": sendText(args[1]); break;
            default: throw new IllegalArgumentException(mode);
        }
    }

    static String readHeader(InputStream in) throws Exception {
        if (!java.util.Arrays.equals(Proto.readExact(in, 4), Proto.MAGIC))
            throw new IOException("MAGIC mismatch");
        int hlen = (int) Proto.fromU32(Proto.readExact(in, 4), 0);
        String h = Proto.readString(in, hlen);
        System.out.println("HEADER=" + h);
        return h;
    }

    static void ack(OutputStream out, String msg) throws Exception {
        byte[] m = Proto.utf8(msg);
        out.write(new byte[]{1});
        out.write(Proto.u32(m.length));
        out.write(m);
        out.flush();
    }

    static void recvFile(Path dir) throws Exception {
        ServerSocket srv = new ServerSocket(Proto.TCP_PORT);
        srv.setSoTimeout(15000);
        Socket s = srv.accept();
        s.setSoTimeout(15000);
        InputStream in = s.getInputStream();
        String header = readHeader(in);
        Matcher m = Pattern.compile("\"size\":(\\d+)").matcher(header);
        long size = m.find() ? Long.parseLong(m.group(1)) : 0;
        byte[] data = Proto.readExact(in, (int) size);
        long crc = Proto.fromU32(Proto.readExact(in, 4), 0);
        CRC32 c = new CRC32();
        c.update(data);
        if (c.getValue() != crc) throw new IOException("CRC mismatch");
        Files.createDirectories(dir);
        Files.write(dir.resolve("from_python.bin"), data);
        System.out.println("RECV_OK bytes=" + data.length + " crc=" + crc);
        ack(s.getOutputStream(), "已接收");
        s.close(); srv.close();
    }

    static void recvText() throws Exception {
        ServerSocket srv = new ServerSocket(Proto.TCP_PORT);
        srv.setSoTimeout(15000);
        Socket s = srv.accept();
        s.setSoTimeout(15000);
        String header = readHeader(s.getInputStream());
        Matcher m = Pattern.compile("\"text\":\"([^\"]*)\"").matcher(header);
        String text = m.find() ? m.group(1) : "";
        System.out.println("TEXT_OK=" + text);
        ack(s.getOutputStream(), "文字已送达");
        s.close(); srv.close();
    }

    static String jsonEscape(String s) {
        return s.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n");
    }

    static Socket connect() throws Exception {
        Socket s = new Socket();
        s.connect(new InetSocketAddress("127.0.0.1", Proto.TCP_PORT), 5000);
        s.setSoTimeout(15000);
        return s;
    }

    static void printAck(Socket s) throws Exception {
        InputStream in = s.getInputStream();
        int status = in.read();
        int mlen = (int) Proto.fromU32(Proto.readExact(in, 4), 0);
        String msg = Proto.readString(in, mlen);
        System.out.println("SEND_OK status=" + status + " msg=" + msg);
        if (status != 1) throw new IOException("receiver rejected");
        s.close();
    }

    static void sendFile(Path src) throws Exception {
        byte[] data = Files.readAllBytes(src);
        CRC32 c = new CRC32();
        c.update(data);
        String header = "{\"v\":1,\"kind\":\"files\",\"from\":\"JavaPeer\","
                + "\"entries\":[{\"rel\":\"from_java.txt\",\"size\":" + data.length
                + ",\"dir\":false}],\"total\":" + data.length + "}";
        byte[] hb = Proto.utf8(header);
        Socket s = connect();
        OutputStream out = s.getOutputStream();
        out.write(Proto.MAGIC);
        out.write(Proto.u32(hb.length));
        out.write(hb);
        out.write(data);
        out.write(Proto.u32(c.getValue()));
        out.flush();
        printAck(s);
    }

    static void sendText(String text) throws Exception {
        String header = "{\"v\":1,\"kind\":\"text\",\"from\":\"JavaPeer\",\"text\":\""
                + jsonEscape(text) + "\"}";
        byte[] hb = Proto.utf8(header);
        Socket s = connect();
        OutputStream out = s.getOutputStream();
        out.write(Proto.MAGIC);
        out.write(Proto.u32(hb.length));
        out.write(hb);
        out.flush();
        printAck(s);
    }
}
