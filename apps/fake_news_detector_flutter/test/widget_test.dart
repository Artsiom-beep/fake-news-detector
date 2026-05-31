import 'dart:typed_data';

import 'package:fake_news_detector_flutter/api_client.dart';
import 'package:fake_news_detector_flutter/main.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  test('metadata-only image signals use a weak-clues mobile status', () {
    const result = FactCheckResult({
      'verdict': 'uncertain',
      'confidence': 0.34,
      'claim': 'JPEG_20260531_192703_7711461984257405998.jpg',
      'summary': 'The lightweight cloud check found no strong AI markers.',
      'image_analysis': {
        'mode': 'ai_image_detection',
        'ai_label': 'uncertain',
        'ai_generated_score': 0.40,
        'reasons': ['android_exported_jpeg_without_camera_metadata'],
        'warnings': ['limited_metadata_only_ai_check'],
      },
    });

    expect(result.statusView.label, 'Weak file clues');
    expect(result.statusView.tone, StatusTone.neutral);
  });

  test('generator and camera metadata use explicit mobile statuses', () {
    const aiMetadata = FactCheckResult({
      'verdict': 'uncertain',
      'confidence': 0.55,
      'claim': 'generated.png',
      'summary': 'AI-generator metadata was found.',
      'image_analysis': {
        'mode': 'ai_image_detection',
        'ai_label': 'likely_ai',
        'ai_generated_score': 0.92,
        'reasons': ['ai_metadata_marker=stable diffusion'],
        'warnings': <String>[],
      },
    });
    const cameraMetadata = FactCheckResult({
      'verdict': 'uncertain',
      'confidence': 0.50,
      'claim': 'photo.jpg',
      'summary': 'Original camera metadata was found.',
      'image_analysis': {
        'mode': 'ai_image_detection',
        'ai_label': 'uncertain',
        'ai_generated_score': 0.08,
        'reasons': ['camera_metadata_present=make,model'],
        'warnings': ['ai_image_detection_not_definitive'],
      },
    });
    const missingMetadata = FactCheckResult({
      'verdict': 'uncertain',
      'confidence': 0.34,
      'claim': 'download.jpg',
      'summary': 'No original metadata was found.',
      'image_analysis': {
        'mode': 'ai_image_detection',
        'ai_label': 'uncertain',
        'ai_generated_score': 0.26,
        'reasons': ['optional_ai_image_model_disabled'],
        'warnings': ['camera_metadata_missing_not_proof'],
      },
    });

    expect(aiMetadata.statusView.label, 'AI metadata found');
    expect(aiMetadata.statusView.scoreLabel, 'Metadata risk');
    expect(cameraMetadata.statusView.label, 'Camera metadata found');
    expect(cameraMetadata.statusView.tone, StatusTone.good);
    expect(missingMetadata.statusView.label, 'Metadata missing');
  });

  testWidgets('Facts mode submits a claim and renders the verdict',
      (tester) async {
    final gateway = FakeGateway();
    await tester.pumpWidget(FakeNewsDetectorApp(gateway: gateway));

    await tester.tap(find.text('Facts'));
    await tester.pumpAndSettle();

    await tester.enterText(
        find.byType(TextField).first, 'Elephant is a mammal');
    await tester.tap(find.text('Check fact'));
    await tester.pumpAndSettle();

    expect(gateway.lastText, 'Elephant is a mammal');
    expect(find.text('Likely reliable'), findsOneWidget);
    expect(find.text('The claim is supported.'), findsOneWidget);
  });

  testWidgets('Image modes show a friendly missing-file error', (tester) async {
    await tester.pumpWidget(FakeNewsDetectorApp(gateway: FakeGateway()));

    expect(find.text('Screenshots'), findsNothing);
    expect(find.text('Check screenshot'), findsNothing);

    await tester.tap(find.text('Images'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Check metadata'));
    await tester.pumpAndSettle();

    expect(find.text('Choose an image first.'), findsOneWidget);
  });

  testWidgets('News mode renders credibility details from the API',
      (tester) async {
    final gateway = FakeGateway(
      textResult: const FactCheckResult({
        'verdict': 'uncertain',
        'confidence': 0.72,
        'claim': 'Official agency release',
        'summary':
            'News credibility is high (0.72). This is a credibility assessment.',
        'evidence': <Map<String, dynamic>>[],
        'credibility': {
          'score': 0.72,
          'label': 'high',
          'source_score': 0.94,
          'article_quality_score': 0.74,
          'corroboration_score': 0.0,
          'risk_score': 0.31,
          'matched_sources': <Map<String, dynamic>>[],
          'risk_flags': ['missing_author', 'no_independent_corroboration'],
        },
      }),
    );
    await tester.pumpWidget(FakeNewsDetectorApp(gateway: gateway));

    await tester.enterText(
        find.byType(TextField).first, 'https://example.gov/news/item');
    await tester.tap(find.text('Check news'));
    await tester.pumpAndSettle();

    expect(gateway.lastUrl, 'https://example.gov/news/item');
    expect(find.text('Credibility: high'), findsOneWidget);
    expect(find.text('News credibility'), findsOneWidget);
    expect(find.text('Source 94%'), findsOneWidget);
    expect(find.text('Article 74%'), findsOneWidget);
    expect(
        find.text('Risk flags: missing_author, no_independent_corroboration'),
        findsOneWidget);
  });

  testWidgets('Result card renders image warnings and OCR confidence',
      (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.theme,
        home: const Scaffold(
          body: ResultCard(
            result: FactCheckResult({
              'verdict': 'fake',
              'confidence': 0.78,
              'claim': 'Elephants are insects',
              'summary': 'Evidence refutes the claim.',
              'image_analysis': {
                'mode': 'screenshot_ocr',
                'ocr_text': 'Joe Biden is president',
                'ocr_confidence': 0.98,
                'warnings': ['ocr_low_contrast'],
                'reasons': ['ocr_lines=1'],
              },
            }),
          ),
        ),
      ),
    );

    expect(find.text('Screenshot text'), findsOneWidget);
    expect(find.text('OCR confidence: 98%'), findsOneWidget);
    expect(find.text('Joe Biden is president'), findsOneWidget);
    expect(find.text('Warnings: ocr_low_contrast'), findsOneWidget);
  });

  testWidgets('API settings save a reusable backend URL', (tester) async {
    SharedPreferences.setMockInitialValues({});
    await tester
        .pumpWidget(const FakeNewsDetectorApp(enableBackendStatus: false));
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('API settings'));
    await tester.pumpAndSettle();
    await tester.enterText(
        find.byType(TextField).last, 'https://demo.onrender.com/');
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();

    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getString('api_base_url'), 'https://demo.onrender.com');
    expect(find.text('API URL saved'), findsOneWidget);
  });

  testWidgets('API settings reject incomplete backend URLs', (tester) async {
    SharedPreferences.setMockInitialValues({});
    await tester
        .pumpWidget(const FakeNewsDetectorApp(enableBackendStatus: false));
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('API settings'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).last, 'demo.onrender.com');
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();

    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getString('api_base_url'), isNull);
    expect(
      find.text(
          'Enter a full API URL, for example https://your-app.onrender.com'),
      findsOneWidget,
    );
  });

  testWidgets('Backend status banner checks and refreshes API health',
      (tester) async {
    final gateway = FakeGateway(
      healthStatuses: [
        const ApiHealthStatus.online(
          service: 'factcheck',
          message: 'Connected',
        ),
        const ApiHealthStatus.offline(
          message: 'API is not reachable from this device.',
        ),
      ],
    );

    await tester.pumpWidget(FakeNewsDetectorApp(gateway: gateway));
    await tester.pumpAndSettle();

    expect(find.text('API connected'), findsOneWidget);
    expect(find.text('Connected to factcheck'), findsOneWidget);

    await tester.tap(find.byTooltip('Check API connection'));
    await tester.pumpAndSettle();

    expect(find.text('API not reachable'), findsOneWidget);
    expect(find.text('API is not reachable from this device.'), findsOneWidget);
    expect(gateway.healthCheckCount, 2);
  });

  test('public build default replaces a saved local API URL', () {
    expect(normalizeApiBaseUrl('https://demo.onrender.com/'),
        'https://demo.onrender.com');
    expect(validateApiBaseUrl('https://demo.onrender.com'), isNull);
    expect(validateApiBaseUrl('http://192.168.1.16:8001'), isNull);
    expect(validateApiBaseUrl('demo.onrender.com'), isNotNull);
    expect(validateApiBaseUrl('ftp://demo.onrender.com'), isNotNull);
    expect(isLocalOrPrivateApiUrl('http://192.168.1.16:8001'), isTrue);
    expect(isLocalOrPrivateApiUrl('http://10.0.2.2:8001'), isTrue);
    expect(isPublicInternetApiUrl('https://demo.onrender.com'), isTrue);
    expect(
      shouldPreferBuildDefaultApiUrl(
        savedUrl: 'http://192.168.1.16:8001',
        buildDefaultUrl: 'https://demo.onrender.com',
      ),
      isTrue,
    );
    expect(
      shouldPreferBuildDefaultApiUrl(
        savedUrl: 'https://custom-api.example.com',
        buildDefaultUrl: 'https://demo.onrender.com',
      ),
      isFalse,
    );
  });

  test('FactCheckApiClient reports invalid API JSON clearly', () async {
    final client = FactCheckApiClient(
      baseUrl: 'https://demo.onrender.com',
      httpClient: MockClient(
        (_) async => http.Response('not-json', 200),
      ),
    );

    await expectLater(
      client.checkText(text: 'Elephant is a mammal'),
      throwsA(
        isA<FactCheckApiException>().having(
          (error) => error.message,
          'message',
          contains('invalid JSON'),
        ),
      ),
    );
  });

  test('FactCheckApiClient reports request timeouts clearly', () async {
    final client = FactCheckApiClient(
      baseUrl: 'https://demo.onrender.com',
      textTimeout: const Duration(milliseconds: 1),
      httpClient: MockClient((_) async {
        await Future<void>.delayed(const Duration(milliseconds: 25));
        return http.Response('{"verdict":"uncertain"}', 200);
      }),
    );

    await expectLater(
      client.checkText(text: 'Elephant is a mammal'),
      throwsA(
        isA<FactCheckApiException>().having(
          (error) => error.message,
          'message',
          contains('timed out'),
        ),
      ),
    );
  });

  test('FactCheckApiClient health check reports invalid JSON offline',
      () async {
    final client = FactCheckApiClient(
      baseUrl: 'https://demo.onrender.com',
      httpClient: MockClient(
        (_) async => http.Response('<html>bad gateway</html>', 200),
      ),
    );

    final status = await client.checkHealth();

    expect(status.isReachable, isFalse);
    expect(status.message, contains('invalid JSON'));
  });
}

class FakeGateway implements FactCheckGateway {
  FakeGateway({
    this.textResult,
    this.imageResult,
    List<ApiHealthStatus>? healthStatuses,
  }) : healthStatuses = healthStatuses ??
            const [
              ApiHealthStatus.online(
                service: 'factcheck',
                message: 'Connected',
              ),
            ];

  final FactCheckResult? textResult;
  final FactCheckResult? imageResult;
  final List<ApiHealthStatus> healthStatuses;
  String? lastText;
  String? lastUrl;
  int healthCheckCount = 0;

  @override
  Future<ApiHealthStatus> checkHealth() async {
    final index = healthCheckCount < healthStatuses.length
        ? healthCheckCount
        : healthStatuses.length - 1;
    healthCheckCount += 1;
    return healthStatuses[index];
  }

  @override
  Future<FactCheckResult> checkText({String text = '', String url = ''}) async {
    lastText = text;
    lastUrl = url;
    return textResult ??
        FactCheckResult({
          'verdict': 'true',
          'confidence': 0.91,
          'claim': text,
          'summary': 'The claim is supported.',
          'evidence': [
            {
              'title': 'Knowledge source',
              'domain': 'wikipedia.org',
              'stance': 'support',
            },
          ],
          'trace': {
            'decision_reasons': <String>[],
            'fallbacks_used': <String>[],
            'stage_timings_ms': <String, dynamic>{},
          },
        });
  }

  @override
  Future<FactCheckResult> checkImage({
    required Uint8List bytes,
    required String filename,
    required ImageAnalysisType analysisType,
    String question = '',
  }) async {
    return imageResult ??
        FactCheckResult({
          'verdict': 'uncertain',
          'confidence': 0.2,
          'summary': 'Image checked.',
          'image_analysis': {
            'mode': analysisType == ImageAnalysisType.aiImage
                ? 'ai_image_detection'
                : 'screenshot_ocr',
            'ai_label': 'uncertain',
            'ai_generated_score': 0.2,
          },
        });
  }
}
