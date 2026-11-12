package com.flashdrop.app;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.content.res.AssetFileDescriptor;
import android.database.Cursor;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.ClipDrawable;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.LayerDrawable;
import android.graphics.drawable.StateListDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.provider.DocumentsContract;
import android.provider.OpenableColumns;
import android.text.InputType;
import android.text.method.ScrollingMovementMethod;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;

import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;

/** 单页界面：一个对端、两类功能、一条进度、一份可点的接收文件列表。 */
public class MainActivity extends Activity implements Hub.Listener {
    private static final int REQ_FILES = 101, REQ_TREE = 102, REQ_PERM = 900;
    private static final String P_LOCAL_NET = "android.permission.ACCESS_LOCAL_NETWORK";
    private static final String P_NEARBY_WIFI = "android.permission.NEARBY_WIFI_DEVICES";
    private static final String P_POST_NOTIF = "android.permission.POST_NOTIFICATIONS";

    private static final int BG = 0xFFF3F5FA;
    private static final int CARD = 0xFFFFFFFF;
    private static final int PRIMARY = 0xFF4C6CE8;
    private static final int PRIMARY_DARK = 0xFF3A56C8;
    private static final int INK = 0xFF16203A;
    private static final int MUTED = 0xFF7A869E;
    private static final int LINE = 0xFFE6EAF3;
    private static final int SOFT = 0xFFF5F7FC;
    private static final int GREEN = 0xFF12A150;
    private static final int AMBER = 0xFFB45309;

    private final List<Hub.Item> items = new ArrayList<>();
    private List<Hub.Peer> peers = new ArrayList<>();
    private Hub.Peer current;
    private boolean busy = false;
    private Object[] lastSend;

    private TextView peerName, peerStatus, selectedText, selectedCount, status, logView,
            receivedCount, quickReceived;
    private ScrollView scrollView;
    private LinearLayout receivedCard;
    private EditText textBox;
    private Button sendFileBtn, sendTextBtn, retryBtn;
    private ProgressBar progress;
    private LinearLayout receivedList;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setupSystemBars();
        setContentView(buildUi());
        ensurePermissions();
        startService(new Intent(this, RecvService.class));
        Hub.get().setListener(this);
        refreshReceived();
        new android.os.Handler().postDelayed(this::refreshReceived, 1500);
    }

    @Override
    protected void onResume() {
        super.onResume();
        refreshReceived();
    }

    @Override
    protected void onDestroy() {
        Hub.get().setListener(null);
        super.onDestroy();
    }

    @Override
    public void onBackPressed() {
        stopService(new Intent(this, RecvService.class));
        finish();
    }

    private SharedPreferences prefs() {
        return getSharedPreferences("flashdrop", MODE_PRIVATE);
    }

    private void setupSystemBars() {
        getWindow().setStatusBarColor(PRIMARY_DARK);
        getWindow().setNavigationBarColor(BG);
        View d = getWindow().getDecorView();
        d.setSystemUiVisibility(d.getSystemUiVisibility()
                & ~View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR);
    }

    // ------------------------------------------------------------------ 权限
    private void ensurePermissions() {
        List<String> want = new ArrayList<>();
        if (android.os.Build.VERSION.SDK_INT >= 33) {
            want.add(P_POST_NOTIF);
            want.add(P_NEARBY_WIFI);
        }
        want.add(P_LOCAL_NET);
        List<String> missing = new ArrayList<>();
        for (String p : want) {
            if (checkSelfPermission(p) != PackageManager.PERMISSION_GRANTED) missing.add(p);
        }
        if (!missing.isEmpty()) requestPermissions(missing.toArray(new String[0]), REQ_PERM);
    }

    @Override
    public void onRequestPermissionsResult(int req, String[] ps, int[] grants) {
        super.onRequestPermissionsResult(req, ps, grants);
        if (req != REQ_PERM) return;
        for (int i = 0; i < ps.length; i++) {
            if (grants[i] != PackageManager.PERMISSION_GRANTED) {
                appendLog("权限未授予：" + ps[i] + "（可在系统设置里打开，或用「手填 IP」）");
            }
        }
    }

    // ------------------------------------------------------------------ 绘制工具
    private int dp(float v) {
        return (int) (v * getResources().getDisplayMetrics().density + 0.5f);
    }

    private GradientDrawable rect(int color, float radius, int strokeColor, int strokeW) {
        GradientDrawable g = new GradientDrawable();
        g.setColor(color);
        g.setCornerRadius(dp(radius));
        if (strokeW > 0) g.setStroke(strokeW, strokeColor);
        return g;
    }

    private StateListDrawable pressed(Drawable normal, Drawable down) {
        StateListDrawable s = new StateListDrawable();
        s.addState(new int[]{android.R.attr.state_pressed}, down);
        s.addState(new int[]{}, normal);
        return s;
    }

    private Button primaryBtn(String label, View.OnClickListener l) {
        Button b = new Button(this);
        b.setText(label);
        b.setAllCaps(false);
        b.setTextSize(14);
        b.setTextColor(0xFFFFFFFF);
        b.setTypeface(Typeface.DEFAULT_BOLD);
        b.setPadding(dp(14), dp(12), dp(14), dp(12));
        b.setMinHeight(0);
        b.setMinimumHeight(0);
        b.setBackground(pressed(rect(PRIMARY, 12, 0, 0), rect(PRIMARY_DARK, 12, 0, 0)));
        b.setOnClickListener(l);
        return b;
    }

    private Button ghostBtn(String label, View.OnClickListener l) {
        Button b = new Button(this);
        b.setText(label);
        b.setAllCaps(false);
        b.setTextSize(12);
        b.setTextColor(INK);
        b.setPadding(dp(12), dp(9), dp(12), dp(9));
        b.setMinHeight(0);
        b.setMinimumHeight(0);
        b.setBackground(pressed(rect(0xFFFFFFFF, 10, LINE, dp(1)),
                rect(SOFT, 10, LINE, dp(1))));
        b.setOnClickListener(l);
        return b;
    }

    private TextView tv(String s, float size, int color, boolean bold) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(size);
        t.setTextColor(color);
        if (bold) t.setTypeface(Typeface.DEFAULT_BOLD);
        return t;
    }

    private LinearLayout.LayoutParams lp(int top) {
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        p.topMargin = dp(top);
        return p;
    }

    private LinearLayout row(int gravity) {
        LinearLayout r = new LinearLayout(this);
        r.setOrientation(LinearLayout.HORIZONTAL);
        r.setGravity(gravity);
        return r;
    }

    private LinearLayout card() {
        LinearLayout c = new LinearLayout(this);
        c.setOrientation(LinearLayout.VERTICAL);
        c.setBackground(rect(CARD, 16, LINE, dp(1)));
        c.setPadding(dp(15), dp(15), dp(15), dp(15));
        c.setElevation(dp(2));
        return c;
    }

    private View section(String title, String hint) {
        LinearLayout r = row(Gravity.CENTER_VERTICAL);
        r.setPadding(0, dp(20), 0, dp(9));
        View bar = new View(this);
        bar.setBackground(rect(PRIMARY, 2, 0, 0));
        LinearLayout.LayoutParams bp = new LinearLayout.LayoutParams(dp(3), dp(15));
        bp.rightMargin = dp(8);
        r.addView(bar, bp);
        r.addView(tv(title, 14, INK, true));
        TextView h = tv(hint, 10, MUTED, false);
        LinearLayout.LayoutParams hp = new LinearLayout.LayoutParams(
                0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        h.setGravity(Gravity.END);
        r.addView(h, hp);
        return r;
    }

    private View buildUi() {
        ScrollView scroll = new ScrollView(this);
        scrollView = scroll;
        scroll.setBackgroundColor(BG);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(16), dp(14), dp(16), dp(26));
        scroll.addView(root, new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        // ---------- 顶部品牌卡 ----------
        GradientDrawable heroBg = new GradientDrawable(
                GradientDrawable.Orientation.LEFT_RIGHT,
                new int[]{0xFF6283FA, 0xFF3C58D4});
        heroBg.setCornerRadius(dp(20));
        LinearLayout hero = new LinearLayout(this);
        hero.setOrientation(LinearLayout.VERTICAL);
        hero.setBackground(heroBg);
        hero.setPadding(dp(18), dp(18), dp(18), dp(16));
        hero.setElevation(dp(5));
        root.addView(hero, lp(0));

        LinearLayout heroTop = row(Gravity.CENTER_VERTICAL);
        TextView mark = tv("↓", 20, 0xFFFFFFFF, true);
        mark.setGravity(Gravity.CENTER);
        GradientDrawable markBg = new GradientDrawable();
        markBg.setColor(0x33FFFFFF);
        markBg.setCornerRadius(dp(13));
        mark.setBackground(markBg);
        heroTop.addView(mark, new LinearLayout.LayoutParams(dp(42), dp(42)));
        LinearLayout titles = new LinearLayout(this);
        titles.setOrientation(LinearLayout.VERTICAL);
        LinearLayout.LayoutParams tp = new LinearLayout.LayoutParams(0,
                ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        tp.leftMargin = dp(12);
        titles.addView(tv("FlashDrop", 21, 0xFFFFFFFF, true));
        titles.addView(tv("局域网 · 文件与文字极速互传", 11, 0xCCFFFFFF, false));
        heroTop.addView(titles, tp);
        TextView live = tv("● 接收中", 10, 0xFFE8FFF1, true);
        live.setBackground(rect(0x33FFFFFF, 20, 0, 0));
        live.setPadding(dp(10), dp(5), dp(10), dp(5));
        heroTop.addView(live);
        hero.addView(heroTop);

        TextView meta = tv("本机 " + Hub.localIp() + "　·　收件目录 Download/FlashDrop",
                10, 0xCCFFFFFF, false);
        meta.setPadding(0, dp(14), 0, 0);
        hero.addView(meta);

        // ---------- 安全提示 ----------
        TextView warn = tv("⚠  仅家庭私有 WiFi 使用 · 同网段任何设备都可向本机投递，内容不加密",
                10, AMBER, false);
        warn.setBackground(rect(0xFFFFF6E6, 12, 0xFFF7DFB0, dp(1)));
        warn.setPadding(dp(12), dp(10), dp(12), dp(10));
        root.addView(warn, lp(12));

        quickReceived = tv("已接收 0 个文件 · 点击查看  ↗", 11, PRIMARY, true);
        quickReceived.setBackground(pressed(rect(0xFFE9EEFF, 12, 0, 0),
                rect(0xFFDCE5FF, 12, 0, 0)));
        quickReceived.setPadding(dp(12), dp(11), dp(12), dp(11));
        quickReceived.setGravity(Gravity.CENTER);
        quickReceived.setOnClickListener(v -> {
            if (scrollView != null && receivedCard != null) {
                scrollView.smoothScrollTo(0, Math.max(0, receivedCard.getTop() - dp(12)));
            }
        });
        root.addView(quickReceived, lp(10));

        // ---------- 连接 ----------
        root.addView(section("连接", "自动发现"));
        LinearLayout c1 = card();
        root.addView(c1, lp(0));
        LinearLayout peerHead = row(Gravity.CENTER_VERTICAL);
        peerHead.addView(tv("当前对端", 11, MUTED, false),
                new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        peerStatus = tv("● 未发现", 10, MUTED, true);
        peerHead.addView(peerStatus);
        c1.addView(peerHead);

        peerName = tv("点击选择对端", 16, INK, true);
        peerName.setBackground(pressed(rect(SOFT, 12, LINE, dp(1)), rect(0xFFE9EEFB, 12, LINE, dp(1))));
        peerName.setPadding(dp(14), dp(14), dp(14), dp(14));
        peerName.setGravity(Gravity.CENTER_VERTICAL);
        peerName.setCompoundDrawablesWithIntrinsicBounds(0, 0,
                android.R.drawable.arrow_down_float, 0);
        peerName.setOnClickListener(v -> showPeerPicker());
        c1.addView(peerName, lp(10));

        LinearLayout c1row = row(Gravity.CENTER_VERTICAL);
        c1row.setPadding(0, dp(10), 0, 0);
        c1row.addView(ghostBtn("手填 IP", v -> askIp()));
        TextView helper = tv("两端打开 App 即自动连上", 10, MUTED, false);
        LinearLayout.LayoutParams hp2 = new LinearLayout.LayoutParams(
                0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        helper.setGravity(Gravity.END);
        c1row.addView(helper, hp2);
        c1.addView(c1row);

        // ---------- 发送：文件 ----------
        root.addView(section("发送", "文件 / 文件夹"));
        LinearLayout c2 = card();
        root.addView(c2, lp(0));
        LinearLayout c2head = row(Gravity.CENTER_VERTICAL);
        c2head.addView(tv("待发送", 12, INK, true),
                new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        selectedCount = tv("0 项", 10, MUTED, false);
        c2head.addView(selectedCount);
        c2.addView(c2head);
        selectedText = tv("还没有选择文件", 11, MUTED, false);
        selectedText.setBackground(rect(SOFT, 10, LINE, dp(1)));
        selectedText.setPadding(dp(12), dp(12), dp(12), dp(12));
        selectedText.setMinLines(2);
        selectedText.setMaxLines(4);
        c2.addView(selectedText, lp(9));

        LinearLayout c2row = row(Gravity.CENTER_VERTICAL);
        c2row.setPadding(0, dp(11), 0, 0);
        c2row.addView(ghostBtn("选文件", v -> pickFiles()));
        c2row.addView(spacer(6));
        c2row.addView(ghostBtn("选文件夹", v -> pickTree()));
        c2row.addView(spacer(6));
        c2row.addView(ghostBtn("清空", v -> { items.clear(); refreshSelected(); }));
        c2.addView(c2row);
        sendFileBtn = primaryBtn("发送到 …", v -> sendFiles());
        c2.addView(sendFileBtn, lp(13));

        // ---------- 发送：文字 ----------
        LinearLayout c3 = card();
        root.addView(c3, lp(11));
        c3.addView(tv("文字 · 收到后自动进剪贴板", 12, INK, true));
        textBox = new EditText(this);
        textBox.setHint("把要发送的文字粘贴到这里…");
        textBox.setTextSize(13);
        textBox.setTextColor(INK);
        textBox.setHintTextColor(MUTED);
        textBox.setGravity(Gravity.TOP);
        textBox.setMinLines(3);
        textBox.setMaxLines(5);
        textBox.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE);
        textBox.setBackground(rect(SOFT, 10, LINE, dp(1)));
        textBox.setPadding(dp(12), dp(10), dp(12), dp(10));
        c3.addView(textBox, lp(10));
        sendTextBtn = primaryBtn("发送文字到 …", v -> sendText());
        c3.addView(sendTextBtn, lp(11));

        // ---------- 接收文件 ----------
        root.addView(section("接收", "Download/FlashDrop"));
        LinearLayout c4 = card();
        receivedCard = c4;
        root.addView(c4, lp(0));
        LinearLayout c4head = row(Gravity.CENTER_VERTICAL);
        c4head.addView(tv("已接收文件", 12, INK, true),
                new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        receivedCount = tv("0 个", 10, MUTED, false);
        c4head.addView(receivedCount);
        c4head.addView(spacer(8));
        c4head.addView(ghostBtn("刷新", v -> refreshReceived()));
        c4.addView(c4head);
        receivedList = new LinearLayout(this);
        receivedList.setOrientation(LinearLayout.VERTICAL);
        c4.addView(receivedList, lp(8));
        Button openFolder = ghostBtn("打开接收文件夹  ↗", v -> openReceivedFolder());
        c4.addView(openFolder, lp(10));

        // ---------- 进度 / 状态 / 日志 ----------
        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progress.setMax(100);
        GradientDrawable track = rect(0xFFE8ECF7, 8, 0, 0);
        GradientDrawable fill = rect(PRIMARY, 8, 0, 0);
        ClipDrawable clip = new ClipDrawable(fill, Gravity.START, ClipDrawable.HORIZONTAL);
        LayerDrawable layer = new LayerDrawable(new Drawable[]{track, clip});
        layer.setId(0, android.R.id.background);
        layer.setId(1, android.R.id.progress);
        progress.setProgressDrawable(layer);
        LinearLayout.LayoutParams pp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(8));
        pp.topMargin = dp(20);
        root.addView(progress, pp);

        status = tv("就绪", 12, INK, true);
        root.addView(status, lp(9));
        retryBtn = ghostBtn("重试上一次发送", v -> { if (lastSend != null) doSend(); });
        retryBtn.setVisibility(View.GONE);
        root.addView(retryBtn, lp(8));

        LinearLayout logCard = new LinearLayout(this);
        logCard.setOrientation(LinearLayout.VERTICAL);
        logCard.setBackground(rect(0xFFEDF1F9, 12, 0, 0));
        logCard.setPadding(dp(12), dp(10), dp(12), dp(10));
        root.addView(logCard, lp(14));
        logCard.addView(tv("运行日志", 10, MUTED, true));
        logView = tv("", 9, MUTED, false);
        logView.setMaxLines(7);
        logView.setMovementMethod(new ScrollingMovementMethod());
        logCard.addView(logView, lp(5));

        Button exit = primaryBtn("退出并停止接收", v -> onBackPressed());
        exit.setBackground(pressed(rect(0xFFE9EDF7, 12, 0, 0), rect(0xFFDDE4F3, 12, 0, 0)));
        exit.setTextColor(INK);
        root.addView(exit, lp(16));
        return scroll;
    }

    private View spacer(int w) {
        View v = new View(this);
        v.setLayoutParams(new LinearLayout.LayoutParams(dp(w), 1));
        return v;
    }

    private void appendLog(String s) {
        String old = logView.getText().toString();
        String[] lines = (old + s + "\n").split("\n");
        StringBuilder b = new StringBuilder();
        for (int i = Math.max(0, lines.length - 25); i < lines.length; i++)
            b.append(lines[i]).append('\n');
        logView.setText(b.toString());
    }

    private void setStatus(String s, boolean error) {
        status.setText(s);
        status.setTextColor(error ? 0xFFDC2626 : INK);
    }

    // ------------------------------------------------------------------ 对端
    @Override
    public void onPeers(List<Hub.Peer> list) {
        peers = list;
        if (list.isEmpty()) {
            current = null;
            peerName.setText("点击选择对端");
            peerStatus.setText("● 未发现");
            peerStatus.setTextColor(MUTED);
        } else {
            String keep = prefs().getString("last_peer_id", "");
            int idx = -1;
            for (int i = 0; i < list.size(); i++) if (list.get(i).id.equals(keep)) idx = i;
            if (idx < 0 && list.size() == 1) idx = 0;
            if (idx < 0) idx = 0;
            current = list.get(idx);
            prefs().edit().putString("last_peer_id", current.id).apply();
            peerName.setText(current.name);
            peerStatus.setText("● " + list.size() + " 个在线");
            peerStatus.setTextColor(GREEN);
        }
        updateButtons();
    }

    private void updateButtons() {
        String name = current == null ? "…" : current.name;
        sendFileBtn.setText("发送到 " + name + "   →");
        sendTextBtn.setText("发送文字到 " + name + "   →");
    }

    private void showPeerPicker() {
        if (peers.isEmpty()) {
            new AlertDialog.Builder(this)
                    .setTitle("没有发现对端")
                    .setMessage("请先在电脑上打开 FlashDrop，两端连接同一个 WiFi。也可以手动输入电脑的 IP。")
                    .setPositiveButton("手填 IP", (d, w) -> askIp())
                    .setNegativeButton("关闭", null).show();
            return;
        }
        String[] names = new String[peers.size()];
        for (int i = 0; i < peers.size(); i++) names[i] = peers.get(i).label();
        new AlertDialog.Builder(this)
                .setTitle("选择对端")
                .setItems(names, (d, which) -> {
                    if (which >= 0 && which < peers.size()) {
                        current = peers.get(which);
                        prefs().edit().putString("last_peer_id", current.id).apply();
                        peerName.setText(current.name);
                        updateButtons();
                        setStatus("已选择 " + current.name, false);
                    }
                })
                .setNegativeButton("手填 IP", (d, w) -> askIp())
                .show();
    }

    private void askIp() {
        final EditText e = new EditText(this);
        e.setHint("例如 192.168.27.151");
        e.setInputType(InputType.TYPE_CLASS_TEXT);
        e.setPadding(dp(16), dp(10), dp(16), dp(10));
        new AlertDialog.Builder(this)
                .setTitle("手填 IP")
                .setMessage("输入对端的局域网 IP，自动发现失败时使用。")
                .setView(e)
                .setPositiveButton("确定", (d, w) -> Hub.get().ping(e.getText().toString()))
                .setNegativeButton("取消", null)
                .show();
    }

    // ------------------------------------------------------------------ 选文件
    private void pickFiles() {
        Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        i.addCategory(Intent.CATEGORY_OPENABLE);
        i.setType("*/*");
        i.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
        i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION
                | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
        startActivityForResult(i, REQ_FILES);
    }

    private void pickTree() {
        Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
        i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION
                | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
        startActivityForResult(i, REQ_TREE);
    }

    @Override
    protected void onActivityResult(int req, int result, Intent data) {
        super.onActivityResult(req, result, data);
        if (result != RESULT_OK || data == null) return;
        int flags = data.getFlags() & (Intent.FLAG_GRANT_READ_URI_PERMISSION
                | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
        try {
            if (req == REQ_FILES) {
                if (data.getClipData() != null) {
                    ClipData cd = data.getClipData();
                    for (int i = 0; i < cd.getItemCount(); i++) addFile(cd.getItemAt(i).getUri());
                } else if (data.getData() != null) {
                    addFile(data.getData());
                }
            } else if (req == REQ_TREE && data.getData() != null) {
                Uri tree = data.getData();
                getContentResolver().takePersistableUriPermission(tree, flags);
                String rootId = DocumentsContract.getTreeDocumentId(tree);
                String rootName = docName(DocumentsContract.buildDocumentUriUsingTree(tree, rootId));
                if (rootName == null) rootName = "文件夹";
                items.add(new Hub.Item(rootName, 0, true, null));
                walkTree(tree, rootId, rootName);
            }
        } catch (Exception e) {
            appendLog("选择失败：" + e);
        }
        refreshSelected();
    }

    private void addFile(Uri uri) throws Exception {
        getContentResolver().takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION);
        String name = docName(uri);
        if (name == null) name = "文件";
        items.add(new Hub.Item(name, realSize(uri, 0), false, uri));
    }

    private void walkTree(Uri tree, String parentId, String prefix) {
        Uri children = DocumentsContract.buildChildDocumentsUriUsingTree(tree, parentId);
        String[] proj = {
                DocumentsContract.Document.COLUMN_DOCUMENT_ID,
                DocumentsContract.Document.COLUMN_DISPLAY_NAME,
                DocumentsContract.Document.COLUMN_MIME_TYPE,
                DocumentsContract.Document.COLUMN_SIZE
        };
        Cursor c = getContentResolver().query(children, proj, null, null, null);
        if (c == null) return;
        try {
            while (c.moveToNext()) {
                String id = c.getString(0), name = c.getString(1), mime = c.getString(2);
                long size = c.isNull(3) ? 0 : c.getLong(3);
                if (name == null || id == null) continue;
                String rel = prefix + "/" + name;
                Uri child = DocumentsContract.buildDocumentUriUsingTree(tree, id);
                if (DocumentsContract.Document.MIME_TYPE_DIR.equals(mime)) {
                    items.add(new Hub.Item(rel, 0, true, null));
                    walkTree(tree, id, rel);
                } else {
                    items.add(new Hub.Item(rel, realSize(child, size), false, child));
                }
            }
        } finally {
            c.close();
        }
    }

    private String docName(Uri uri) {
        Cursor c = getContentResolver().query(uri,
                new String[]{OpenableColumns.DISPLAY_NAME}, null, null, null);
        if (c == null) return null;
        try {
            return c.moveToFirst() ? c.getString(0) : null;
        } finally { c.close(); }
    }

    private long realSize(Uri uri, long fallback) {
        try {
            AssetFileDescriptor afd = getContentResolver().openAssetFileDescriptor(uri, "r");
            if (afd != null) {
                long n = afd.getLength();
                afd.close();
                if (n >= 0) return n;
            }
        } catch (Exception ignored) {}
        return fallback;
    }

    private void refreshSelected() {
        selectedCount.setText(items.size() + " 项");
        if (items.isEmpty()) {
            selectedText.setText("还没有选择文件");
            return;
        }
        StringBuilder b = new StringBuilder();
        for (int i = 0; i < Math.min(items.size(), 4); i++) {
            b.append(items.get(i).dir ? "▸ [目录] " : "▸ ").append(items.get(i).rel).append('\n');
        }
        if (items.size() > 4) b.append("… 共 ").append(items.size()).append(" 项");
        selectedText.setText(b.toString().trim());
    }

    // ------------------------------------------------------------------ 发送
    private void sendFiles() {
        if (items.isEmpty()) { setStatus("先点「选文件」或「选文件夹」", true); return; }
        lastSend = new Object[]{"files", new ArrayList<>(items)};
        doSend();
    }

    private void sendText() {
        String t = textBox.getText().toString();
        if (t.trim().isEmpty()) { setStatus("文字是空的，先粘贴要发的内容", true); return; }
        lastSend = new Object[]{"text", t};
        doSend();
    }

    @SuppressWarnings("unchecked")
    private void doSend() {
        if (busy) return;
        if (current == null) { setStatus("没有对端：请打开电脑端，或点「手填 IP」", true); return; }
        busy = true;
        sendFileBtn.setEnabled(false);
        sendTextBtn.setEnabled(false);
        retryBtn.setVisibility(View.GONE);
        progress.setProgress(0);
        setStatus("正在发送到 " + current.name + " …", false);
        Hub.Result cb = (ok, msg) -> {
            busy = false;
            sendFileBtn.setEnabled(true);
            sendTextBtn.setEnabled(true);
            setStatus((ok ? "已送达 · " : "发送失败 · ") + msg, !ok);
            if (ok) {
                progress.setProgress(100);
                items.clear(); refreshSelected(); textBox.setText("");
                lastSend = null;
            } else {
                appendLog("发送失败：" + msg);
                retryBtn.setVisibility(View.VISIBLE);
            }
        };
        if ("text".equals(lastSend[0])) {
            Hub.get().sendText((String) lastSend[1], current, cb);
        } else {
            Hub.get().sendFiles((List<Hub.Item>) lastSend[1], current, cb);
        }
    }

    @Override
    public void onProgress(long done, long total) {
        if (total > 0) {
            progress.setProgress((int) Math.min(100, done * 100 / total));
            setStatus(String.format("发送中 %.1f / %.1f MB",
                    done / 1048576.0, total / 1048576.0), false);
        }
    }

    // ------------------------------------------------------------------ 接收
    @Override
    public void onText(String text, String from) {
        try {
            ClipboardManager cm = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
            cm.setPrimaryClip(ClipData.newPlainText("FlashDrop", text));
            textBox.setText(text);
            textBox.setSelection(0);
            textBox.clearFocus();
            setStatus("收到 " + from + " 的文字，已写入剪贴板", false);
        } catch (Exception e) {
            setStatus("收到文字，但写入剪贴板失败：" + e, true);
        }
        appendLog("收到文字：" + text.substring(0, Math.min(60, text.length())));
    }

    @Override
    public void onFiles(int count, String from) {
        setStatus("已收到 " + from + " 的 " + count + " 项", false);
        appendLog("收到 " + count + " 项文件");
        refreshReceived();
    }

    @Override
    public void onLog(String msg) { appendLog(msg); }

    private void refreshReceived() {
        new Thread(() -> {
            final List<Hub.Received> list = Hub.get().receivedFiles();
            runOnUiThread(() -> renderReceived(list));
        }, "fd-list-files").start();
    }

    private void renderReceived(List<Hub.Received> list) {
        receivedList.removeAllViews();
        receivedCount.setText(list.size() + " 个");
        quickReceived.setText("已接收 " + list.size() + " 个文件 · 点击查看  ↗");
        if (list.isEmpty()) {
            TextView empty = tv("还没有收到文件 · 收到后会显示在这里，点一下即可打开",
                    11, MUTED, false);
            empty.setBackground(rect(SOFT, 10, LINE, dp(1)));
            empty.setPadding(dp(12), dp(16), dp(12), dp(16));
            empty.setGravity(Gravity.CENTER);
            receivedList.addView(empty);
            return;
        }
        SimpleDateFormat fmt = new SimpleDateFormat("MM-dd HH:mm", Locale.getDefault());
        for (Hub.Received r : list) renderFileRow(r, fmt);
    }

    private void renderFileRow(Hub.Received r, SimpleDateFormat fmt) {
        LinearLayout line = row(Gravity.CENTER_VERTICAL);
        line.setPadding(dp(9), dp(10), dp(9), dp(10));
        line.setBackground(pressed(rect(0x00000000, 10, 0, 0), rect(SOFT, 10, 0, 0)));
        line.setClickable(true);
        line.setOnClickListener(v -> openReceivedFile(r));

        String ext = "FILE";
        int dot = r.name.lastIndexOf('.');
        if (dot > 0 && r.name.length() - dot <= 5)
            ext = r.name.substring(dot + 1).toUpperCase(Locale.ROOT);
        TextView badge = tv(ext, 9, 0xFFFFFFFF, true);
        badge.setGravity(Gravity.CENTER);
        badge.setBackground(rect(PRIMARY, 9, 0, 0));
        line.addView(badge, new LinearLayout.LayoutParams(dp(40), dp(40)));

        LinearLayout info = new LinearLayout(this);
        info.setOrientation(LinearLayout.VERTICAL);
        LinearLayout.LayoutParams ip = new LinearLayout.LayoutParams(
                0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        ip.leftMargin = dp(11);
        TextView name = tv(r.name, 12, INK, true);
        name.setSingleLine(true);
        info.addView(name);
        String sub = humanSize(r.size)
                + (r.date > 0 ? "  ·  " + fmt.format(new Date(r.date * 1000)) : "")
                + "  ·  " + r.relPath.replace("Download/FlashDrop", "");
        TextView detail = tv(sub, 9, MUTED, false);
        detail.setSingleLine(true);
        info.addView(detail);
        line.addView(info, ip);
        line.addView(tv("›", 20, MUTED, false));
        receivedList.addView(line, lp(4));
    }

    private static String humanSize(long n) {
        if (n < 1024) return n + " B";
        if (n < 1024 * 1024) return String.format(Locale.ROOT, "%.1f KB", n / 1024.0);
        return String.format(Locale.ROOT, "%.1f MB", n / 1048576.0);
    }

    private void openReceivedFile(Hub.Received r) {
        try {
            Intent i = new Intent(Intent.ACTION_VIEW);
            i.setDataAndType(r.uri, r.mime == null ? "*/*" : r.mime);
            i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            startActivity(i);
        } catch (Exception e) {
            setStatus("没有能打开这个文件的 App，试试「打开接收文件夹」", true);
            appendLog("打开文件失败：" + e);
        }
    }

    private void openReceivedFolder() {
        // 依次尝试：系统文件管理器直达 → SAF 目录选择器（定位到 Download）→ 通用下载根目录
        try {
            Uri folder = DocumentsContract.buildDocumentUri(
                    "com.android.externalstorage.documents", "primary:Download/FlashDrop");
            Intent i = new Intent(Intent.ACTION_VIEW);
            i.setDataAndType(folder, DocumentsContract.Document.MIME_TYPE_DIR);
            i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(i);
            return;
        } catch (Exception ignored) {}
        try {
            Uri downloads = DocumentsContract.buildDocumentUri(
                    "com.android.externalstorage.documents", "primary:Download");
            Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
            i.putExtra(DocumentsContract.EXTRA_INITIAL_URI, downloads);
            i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION
                    | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
            startActivity(i);
            return;
        } catch (Exception ignored) {}
        try {
            Intent i = new Intent(Intent.ACTION_VIEW);
            i.setDataAndType(DocumentsContract.buildRootUri(
                    "com.android.externalstorage.documents", "primary"),
                    DocumentsContract.Document.MIME_TYPE_DIR);
            startActivity(i);
        } catch (Exception e) {
            setStatus("打不开文件夹，请用文件管理进入 Download/FlashDrop", true);
            appendLog("打开文件夹失败：" + e);
        }
    }
}
