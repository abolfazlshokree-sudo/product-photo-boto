<?php
error_reporting(0);
ini_set('display_errors', 0);
set_time_limit(0);

$backend = 'http://127.0.0.1:8765';
$path = $_SERVER['PATH_INFO'] ?? $_GET['path'] ?? '/';
$url = $backend . '/files' . $path;

$ch = curl_init($url);
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_HEADER, true);
curl_setopt($ch, CURLOPT_TIMEOUT, 120);
curl_setopt($ch, CURLOPT_FOLLOWLOCATION, false);

$response = curl_exec($ch);
$http_code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
$header_size = curl_getinfo($ch, CURLINFO_HEADER_SIZE);
curl_close($ch);

if ($response === false) {
    http_response_code(502);
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