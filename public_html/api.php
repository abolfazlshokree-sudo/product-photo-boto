<?php
error_reporting(0);
ini_set('display_errors', 0);
set_time_limit(0);
ini_set('max_execution_time', 0);

$backend = 'http://127.0.0.1:8765';

// مسیر
$path = $_SERVER['PATH_INFO'] ?? '';
if (empty($path)) {
    $path = $_GET['path'] ?? '/';
}
$url = $backend . $path;

// کوئری استرینگ
$query = $_SERVER['QUERY_STRING'] ?? '';
if ($query && !isset($_GET['path'])) {
    $url .= '?' . $query;
} elseif ($query && isset($_GET['path'])) {
    parse_str($query, $params);
    unset($params['path']);
    if ($params) {
        $url .= '?' . http_build_query($params);
    }
}

// هدرها
$headers = [];
foreach (getallheaders() as $k => $v) {
    $lower = strtolower($k);
    if ($lower === 'host') continue;
    if ($lower === 'connection') continue;
    if ($lower === 'content-length') continue;
    $headers[] = "$k: $v";
}

// تشخیص نوع درخواست
$content_type = $_SERVER['CONTENT_TYPE'] ?? '';

$ch = curl_init($url);
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_HEADER, true);
curl_setopt($ch, CURLOPT_CUSTOMREQUEST, $_SERVER['REQUEST_METHOD']);
curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);
curl_setopt($ch, CURLOPT_TIMEOUT, 900);
curl_setopt($ch, CURLOPT_CONNECTTIMEOUT, 30);
curl_setopt($ch, CURLOPT_FOLLOWLOCATION, false);

// ============================================================
// اگر multipart/form-data بود → از $_POST + $_FILES بازسازی کن
// ============================================================
if (stripos($content_type, 'multipart/form-data') !== false) {
    $post_fields = [];

    // فیلدهای معمولی
    foreach ($_POST as $k => $v) {
        $post_fields[$k] = $v;
    }

    // فایل‌ها
    foreach ($_FILES as $field => $file) {
        if (is_array($file['name'])) {
            // چند فایل
            $count = count($file['name']);
            for ($i = 0; $i < $count; $i++) {
                if ($file['error'][$i] !== UPLOAD_ERR_OK) continue;
                $post_fields[$field . '[]'] = new CURLFile(
                    $file['tmp_name'][$i],
                    $file['type'][$i],
                    $file['name'][$i]
                );
            }
        } else {
            // یک فایل
            if ($file['error'] === UPLOAD_ERR_OK) {
                $post_fields[$field] = new CURLFile(
                    $file['tmp_name'],
                    $file['type'],
                    $file['name']
                );
            }
        }
    }

    curl_setopt($ch, CURLOPT_POSTFIELDS, $post_fields);
}
// ============================================================
// اگر JSON یا چیز دیگه بود → بدنه‌ی خام
// ============================================================
else {
    $body = file_get_contents('php://input');
    if (!empty($body)) {
        curl_setopt($ch, CURLOPT_POSTFIELDS, $body);
    }
}

$response = curl_exec($ch);
$http_code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
$header_size = curl_getinfo($ch, CURLINFO_HEADER_SIZE);
$curl_error = curl_error($ch);
curl_close($ch);

if ($response === false) {
    http_response_code(502);
    header('Content-Type: application/json');
    echo json_encode(['error' => 'Backend unreachable: ' . $curl_error]);
    exit;
}

$response_headers = substr($response, 0, $header_size);
$response_body = substr($response, $header_size);

foreach (explode("\r\n", $response_headers) as $h) {
    if (stripos($h, 'HTTP/') === 0) continue;
    if (stripos($h, 'Transfer-Encoding') === 0) continue;
    if (stripos($h, 'Connection') === 0) continue;
    if (stripos($h, 'Content-Length') === 0) continue;
    if (stripos($h, 'Content-Encoding') === 0) continue;
    if (empty(trim($h))) continue;
    header($h);
}

http_response_code($http_code);
echo $response_body;