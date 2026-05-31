import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';

const defaultApiBaseUrl = String.fromEnvironment(
  'API_BASE_URL',
  defaultValue: 'http://127.0.0.1:8001',
);

abstract class FactCheckGateway {
  Future<ApiHealthStatus> checkHealth();

  Future<FactCheckResult> checkText({String text = '', String url = ''});

  Future<FactCheckResult> checkImage({
    required Uint8List bytes,
    required String filename,
    required ImageAnalysisType analysisType,
    String question = '',
  });
}

enum ImageAnalysisType {
  screenshot('screenshot'),
  aiImage('ai_image');

  const ImageAnalysisType(this.apiValue);

  final String apiValue;
}

class FactCheckApiClient implements FactCheckGateway {
  FactCheckApiClient({
    required this.baseUrl,
    http.Client? httpClient,
    this.healthTimeout = const Duration(seconds: 8),
    this.textTimeout = const Duration(seconds: 90),
    this.imageTimeout = const Duration(seconds: 120),
  }) : _httpClient = httpClient ?? http.Client();

  factory FactCheckApiClient.fromEnvironment({http.Client? httpClient}) {
    return FactCheckApiClient(
        baseUrl: defaultApiBaseUrl, httpClient: httpClient);
  }

  final String baseUrl;
  final http.Client _httpClient;
  final Duration healthTimeout;
  final Duration textTimeout;
  final Duration imageTimeout;

  Uri _uri(String path) => Uri.parse(baseUrl).resolve(path);

  @override
  Future<ApiHealthStatus> checkHealth() async {
    try {
      final response =
          await _httpClient.get(_uri('/health')).timeout(healthTimeout);
      final decoded = _decodeJsonMap(response.body);
      final service = (decoded['service'] as String?) ?? '';
      final status = (decoded['status'] as String?) ?? '';
      if (response.statusCode >= 200 &&
          response.statusCode < 300 &&
          status.toLowerCase() == 'ok') {
        return ApiHealthStatus.online(
          service: service.isEmpty ? 'factcheck' : service,
          message: 'Connected',
        );
      }
      return ApiHealthStatus.offline(
        message: 'Health check returned HTTP ${response.statusCode}.',
        statusCode: response.statusCode,
      );
    } on TimeoutException {
      return const ApiHealthStatus.offline(
        message: 'API health check timed out. Verify the API URL.',
      );
    } on FormatException {
      return const ApiHealthStatus.offline(
        message: 'API health check returned invalid JSON.',
      );
    } catch (_) {
      return const ApiHealthStatus.offline(
        message: 'API is not reachable from this device.',
      );
    }
  }

  @override
  Future<FactCheckResult> checkText({String text = '', String url = ''}) async {
    try {
      final response = await _httpClient
          .post(
            _uri('/factcheck'),
            headers: const {'content-type': 'application/json'},
            body: jsonEncode({'text': text.trim(), 'url': url.trim()}),
          )
          .timeout(textTimeout);

      return _decodeResponse(response);
    } on FactCheckApiException {
      rethrow;
    } on TimeoutException {
      throw const FactCheckApiException(
        'The API request timed out. Check the API URL or try again.',
      );
    } on FormatException {
      throw const FactCheckApiException(
        'The API returned invalid JSON.',
      );
    } on http.ClientException catch (error) {
      throw FactCheckApiException('Could not reach the API: ${error.message}');
    } catch (_) {
      throw const FactCheckApiException(
        'The API is not reachable from this device. Verify the API URL and internet connection.',
      );
    }
  }

  @override
  Future<FactCheckResult> checkImage({
    required Uint8List bytes,
    required String filename,
    required ImageAnalysisType analysisType,
    String question = '',
  }) async {
    final request = http.MultipartRequest('POST', _uri('/factcheck-image'))
      ..fields['analysis_type'] = analysisType.apiValue
      ..fields['question'] = question.trim()
      ..files.add(
        http.MultipartFile.fromBytes(
          'image_file',
          bytes,
          filename: filename,
          contentType: _mediaTypeForFilename(filename),
        ),
      );

    try {
      final streamed = await _httpClient.send(request).timeout(imageTimeout);
      final response = await http.Response.fromStream(streamed);
      return _decodeResponse(response);
    } on FactCheckApiException {
      rethrow;
    } on TimeoutException {
      throw const FactCheckApiException(
        'The image request timed out. Check the API URL or try again.',
      );
    } on FormatException {
      throw const FactCheckApiException(
        'The API returned invalid JSON.',
      );
    } on http.ClientException catch (error) {
      throw FactCheckApiException('Could not reach the API: ${error.message}');
    } catch (_) {
      throw const FactCheckApiException(
        'The API is not reachable from this device. Verify the API URL and internet connection.',
      );
    }
  }

  FactCheckResult _decodeResponse(http.Response response) {
    final decoded = _decodeJsonMap(response.body);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw FactCheckApiException(_extractError(decoded, response.statusCode));
    }
    return FactCheckResult(decoded);
  }

  Map<String, dynamic> _decodeJsonMap(String body) {
    if (body.isEmpty) {
      return <String, dynamic>{};
    }
    final decoded = jsonDecode(body);
    if (decoded is Map<String, dynamic>) {
      return decoded;
    }
    if (decoded is Map) {
      return decoded.cast<String, dynamic>();
    }
    throw const FormatException('Expected a JSON object.');
  }

  String _extractError(dynamic decoded, int statusCode) {
    if (decoded is Map<String, dynamic>) {
      final detail = decoded['detail'];
      if (detail is Map<String, dynamic> && detail['error'] is String) {
        return detail['error'] as String;
      }
      if (detail is String) {
        return detail;
      }
      if (decoded['error'] is String) {
        return decoded['error'] as String;
      }
    }
    return 'Request failed with status $statusCode.';
  }

  MediaType _mediaTypeForFilename(String filename) {
    final lower = filename.toLowerCase();
    if (lower.endsWith('.jpg') || lower.endsWith('.jpeg')) {
      return MediaType('image', 'jpeg');
    }
    if (lower.endsWith('.webp')) {
      return MediaType('image', 'webp');
    }
    if (lower.endsWith('.bmp')) {
      return MediaType('image', 'bmp');
    }
    if (lower.endsWith('.tif') || lower.endsWith('.tiff')) {
      return MediaType('image', 'tiff');
    }
    return MediaType('image', 'png');
  }
}

class ApiHealthStatus {
  const ApiHealthStatus({
    required this.isReachable,
    required this.message,
    this.service = '',
    this.statusCode,
  });

  const ApiHealthStatus.online({
    required this.message,
    this.service = 'factcheck',
    this.statusCode,
  }) : isReachable = true;

  const ApiHealthStatus.offline({
    required this.message,
    this.service = '',
    this.statusCode,
  }) : isReachable = false;

  final bool isReachable;
  final String message;
  final String service;
  final int? statusCode;
}

class FactCheckApiException implements Exception {
  const FactCheckApiException(this.message);

  final String message;

  @override
  String toString() => message;
}

class FactCheckResult {
  const FactCheckResult(this.raw);

  final Map<String, dynamic> raw;

  String get verdict =>
      (raw['verdict'] as String?)?.toLowerCase() ?? 'uncertain';

  double get confidence => _asDouble(raw['confidence']);

  String get claim => (raw['claim'] as String?) ?? '';

  String get summary => (raw['summary'] as String?) ?? '';

  Map<String, dynamic> get credibility => _asMap(raw['credibility']);

  Map<String, dynamic> get imageAnalysis => _asMap(raw['image_analysis']);

  List<Map<String, dynamic>> get evidence {
    final items = raw['evidence'];
    if (items is! List) {
      return const [];
    }
    return items
        .whereType<Map>()
        .map((item) => item.cast<String, dynamic>())
        .toList(growable: false);
  }

  StatusView get statusView {
    if (imageAnalysis['mode'] == 'ai_image_detection') {
      final label =
          (imageAnalysis['ai_label'] as String?)?.toLowerCase() ?? 'uncertain';
      final score = _asDouble(imageAnalysis['ai_generated_score']);
      if (label == 'likely_ai') {
        return StatusView('Likely AI', StatusTone.bad, score, 'AI risk score');
      }
      if (label == 'likely_not_ai') {
        return StatusView(
            'Likely real', StatusTone.good, score, 'AI risk score');
      }
      return StatusView(
          'Not enough certainty', StatusTone.neutral, score, 'AI risk score');
    }

    if (credibility.isNotEmpty) {
      final label =
          ((credibility['label'] as String?) ?? 'unknown').toLowerCase();
      return StatusView(
        'Credibility: $label',
        switch (label) {
          'high' => StatusTone.good,
          'medium' => StatusTone.warn,
          'low' => StatusTone.bad,
          _ => StatusTone.neutral,
        },
        _asDouble(credibility['score']),
        'Credibility score',
      );
    }

    if (verdict == 'true') {
      return StatusView(
          'Likely reliable', StatusTone.good, confidence, 'Confidence');
    }
    if (verdict == 'fake') {
      return StatusView(
          'Likely false', StatusTone.bad, confidence, 'Confidence');
    }
    return StatusView(
        'Not enough certainty', StatusTone.neutral, confidence, 'Confidence');
  }

  static double _asDouble(dynamic value) {
    if (value is num) {
      return value.toDouble();
    }
    if (value is String) {
      return double.tryParse(value) ?? 0;
    }
    return 0;
  }

  static Map<String, dynamic> _asMap(dynamic value) {
    if (value is Map<String, dynamic>) {
      return value;
    }
    if (value is Map) {
      return value.cast<String, dynamic>();
    }
    return const {};
  }
}

enum StatusTone { good, warn, bad, neutral }

class StatusView {
  const StatusView(this.label, this.tone, this.score, this.scoreLabel);

  final String label;
  final StatusTone tone;
  final double score;
  final String scoreLabel;
}
