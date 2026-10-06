<?php
header('Content-Type: text/plain; charset=utf-8');

echo "=== PHP Status ===\n";
echo "PHP works: YES\n";
echo "PHP version: " . phpversion() . "\n";
echo "cURL enabled: " . (function_exists('curl_init') ? 'YES' : 'NO') . "\n\n";

echo "=== Testing FastAPI on port 8000 ===\n";

$ch = curl_init('http://127.0.0.1:8000/api/debug');
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_TIMEOUT, 10);
$response = curl_exec($ch);
$code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
$err = curl_error($ch);
curl_close($ch);

echo "HTTP Code: $code\n";
echo "cURL Error: " . ($err ?: 'none') . "\n";
echo "Response:\n";
echo $response;