# Product Acceptance Report

- Created: `2026-06-01T13:52:26+00:00`
- Scope: facts, news credibility, screenshot OCR, AI-image risk, API/mobile contract
- Target pass rate: `95.0%`
- Default minimum cases per section: `5`
- Overall: `93/93` = `100.0%`
- Gate: `passed`

## Section Results

| Section | Passed | Total | Minimum | Rate | Gate |
|---|---:|---:|---:|---:|---:|
| api_contract | 11 | 11 | 11 | 100.0% | yes |
| facts | 44 | 44 | 40 | 100.0% | yes |
| images | 11 | 11 | 11 | 100.0% | yes |
| news | 15 | 15 | 15 | 100.0% | yes |
| screenshots | 12 | 12 | 12 | 100.0% | yes |

## Cases

| ID | Section | Pass | Detail |
|---|---|---:|---|
| fact_arithmetic_true | facts | yes | expected verdict=true, got true |
| fact_arithmetic_false | facts | yes | expected verdict=fake, got fake |
| fact_word_arithmetic_true | facts | yes | expected verdict=true, got true |
| fact_word_arithmetic_false | facts | yes | expected verdict=fake, got fake |
| fact_arithmetic_multiplication_true | facts | yes | expected verdict=true, got true |
| fact_arithmetic_division_false | facts | yes | expected verdict=fake, got fake |
| fact_arithmetic_addition_false | facts | yes | expected verdict=fake, got fake |
| fact_numeric_true | facts | yes | expected verdict=true, got true |
| fact_numeric_false | facts | yes | expected verdict=fake, got fake |
| fact_numeric_less_true | facts | yes | expected verdict=true, got true |
| fact_symbolic_comparison_true | facts | yes | expected verdict=true, got true |
| fact_word_numeric_true | facts | yes | expected verdict=true, got true |
| fact_elephant_mammal | facts | yes | expected verdict=true, got true |
| fact_elephant_insect | facts | yes | expected verdict=fake, got fake |
| fact_dog_mammal | facts | yes | expected verdict=true, got true |
| fact_cat_plant | facts | yes | expected verdict=fake, got fake |
| fact_apple_food | facts | yes | expected verdict=true, got true |
| fact_apple_blue | facts | yes | expected verdict=fake, got fake |
| fact_banana_yellow | facts | yes | expected verdict=true, got true |
| fact_banana_blue | facts | yes | expected verdict=fake, got fake |
| fact_cucumber_green | facts | yes | expected verdict=true, got true |
| fact_grass_red | facts | yes | expected verdict=fake, got fake |
| fact_water_liquid | facts | yes | expected verdict=true, got true |
| fact_ice_hot | facts | yes | expected verdict=fake, got fake |
| fact_fire_hot | facts | yes | expected verdict=true, got true |
| fact_snow_cold | facts | yes | expected verdict=true, got true |
| fact_snow_black | facts | yes | expected verdict=fake, got fake |
| fact_rock_edible | facts | yes | expected verdict=fake, got fake |
| fact_capital_true | facts | yes | expected verdict=true, got true |
| fact_capital_false | facts | yes | expected verdict=fake, got fake |
| fact_capital_germany_true | facts | yes | expected verdict=true, got true |
| fact_capital_us_false | facts | yes | expected verdict=fake, got fake |
| fact_capital_usa_true | facts | yes | expected verdict=true, got true |
| fact_capital_poland_true | facts | yes | expected verdict=true, got true |
| fact_orbit_true | facts | yes | expected verdict=true, got true |
| fact_orbit_false | facts | yes | expected verdict=fake, got fake |
| fact_moon_satellite | facts | yes | expected verdict=true, got true |
| fact_moon_cheese | facts | yes | expected verdict=fake, got fake |
| fact_sky_blue | facts | yes | expected verdict=true, got true |
| fact_sky_green | facts | yes | expected verdict=fake, got fake |
| fact_taste_false | facts | yes | expected verdict=fake, got fake |
| fact_taste_true | facts | yes | expected verdict=true, got true |
| fact_medical_abstain | facts | yes | expected verdict=uncertain, got uncertain |
| fact_unsourced_abstain | facts | yes | expected verdict=uncertain, got uncertain |
| news_primary_high_with_corroboration | news | yes | expected credibility in ['high'], got high |
| news_primary_climate_high_with_corroboration | news | yes | expected credibility in ['high'], got high |
| news_institutional_high_without_corroboration | news | yes | expected credibility in ['high'], got high |
| news_primary_medium_without_corroboration | news | yes | expected credibility in ['high', 'medium'], got high |
| news_major_news_medium_without_corroboration | news | yes | expected credibility in ['high', 'medium'], got high |
| news_institutional_health_high_with_matches | news | yes | expected credibility in ['high'], got high |
| news_major_listing_guardrail | news | yes | expected credibility in ['low', 'unknown'], got unknown |
| news_social_guardrail | news | yes | expected credibility in ['unknown'], got unknown |
| news_low_trust_guardrail | news | yes | expected credibility in ['low', 'unknown'], got unknown |
| news_unknown_source_without_matches | news | yes | expected credibility in ['low', 'unknown'], got unknown |
| news_unknown_source_with_two_matches | news | yes | expected credibility in ['high', 'medium'], got medium |
| news_unknown_source_with_three_matches | news | yes | expected credibility in ['high', 'medium'], got medium |
| news_institutional_fda_high_with_matches | news | yes | expected credibility in ['high'], got high |
| news_institutional_eac_high_without_matches | news | yes | expected credibility in ['high'], got high |
| news_social_reddit_guardrail | news | yes | expected credibility in ['unknown'], got unknown |
| screenshot_ocr_fake_claim | screenshots | yes | expected verdict=fake, got fake |
| screenshot_ocr_true_claim | screenshots | yes | expected verdict=true, got true |
| screenshot_ocr_arithmetic_false | screenshots | yes | expected verdict=fake, got fake |
| screenshot_ocr_sky_false | screenshots | yes | expected verdict=fake, got fake |
| screenshot_ocr_moon_false | screenshots | yes | expected verdict=fake, got fake |
| screenshot_ocr_banana_true | screenshots | yes | expected verdict=true, got true |
| screenshot_question_overrides_ocr | screenshots | yes | expected verdict=true, got true |
| screenshot_question_override_fake | screenshots | yes | expected verdict=fake, got fake |
| screenshot_blank_abstains | screenshots | yes | expected verdict=uncertain, got uncertain |
| screenshot_ocr_dog_true | screenshots | yes | expected verdict=true, got true |
| screenshot_ocr_cat_plant_false | screenshots | yes | expected verdict=fake, got fake |
| screenshot_ocr_numeric_true | screenshots | yes | expected verdict=true, got true |
| image_ai_metadata_marker | images | yes | expected ai_label in ['likely_ai'], got likely_ai |
| image_midjourney_metadata_marker | images | yes | expected ai_label in ['likely_ai'], got likely_ai |
| image_dalle_metadata_marker | images | yes | expected ai_label in ['likely_ai'], got likely_ai |
| image_firefly_metadata_marker | images | yes | expected ai_label in ['likely_ai'], got likely_ai |
| image_ideogram_metadata_marker | images | yes | expected ai_label in ['likely_ai'], got likely_ai |
| image_plain_jpeg_no_false_ai | images | yes | expected ai_label in ['likely_not_ai', 'uncertain'], got uncertain |
| image_square_no_metadata_no_false_ai | images | yes | expected ai_label in ['likely_not_ai', 'uncertain'], got uncertain |
| image_camera_metadata_not_proof_of_real | images | yes | expected ai_label in ['likely_not_ai', 'uncertain'], got uncertain |
| image_leonardo_metadata_marker | images | yes | expected ai_label in ['likely_ai'], got likely_ai |
| image_automatic1111_metadata_marker | images | yes | expected ai_label in ['likely_ai'], got likely_ai |
| image_second_plain_jpeg_no_false_ai | images | yes | expected ai_label in ['likely_not_ai', 'uncertain'], got uncertain |
| api_health_ok | api_contract | yes | status_code=200; expected status=ok, got ok |
| api_ready_ok | api_contract | yes | status_code=200; expected status=ready, got ready |
| api_cors_preflight_ok | api_contract | yes | status_code=200; expected status=ok, got ok; methods=GET, POST, OPTIONS |
| api_factcheck_true | api_contract | yes | status_code=200; expected verdict=true, got true |
| api_factcheck_fake | api_contract | yes | status_code=200; expected verdict=fake, got fake |
| api_screenshot_fake | api_contract | yes | status_code=200; expected verdict=fake, got fake |
| api_ai_image_metadata | api_contract | yes | status_code=200; expected ai_label in ['likely_ai'], got likely_ai |
| api_factcheck_empty_rejected | api_contract | yes | status_code=400; expected 400 for missing text/url |
| api_image_invalid_analysis_rejected | api_contract | yes | status_code=400; expected 400 for invalid analysis_type |
| api_image_missing_file_rejected | api_contract | yes | status_code=422; expected client error for missing image_file |
| api_factcheck_get_method_rejected | api_contract | yes | status_code=405; expected 405 for unsupported method |
