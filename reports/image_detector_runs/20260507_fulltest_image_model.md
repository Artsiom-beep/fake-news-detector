# AI Image Detector Eval

Run ID: `20260507_fulltest_image_model`
Dataset: `data\image_eval\v1\manifest.jsonl`
Model: `haywoodsloan/ai-image-detector-deploy`

Sources:
- AI-generated images and real images are listed in the versioned manifest.
- False `likely_ai` labels on real images are tracked separately because they are the highest-risk failure mode.

Manifest cases: 13
Evaluated cases: 13
Not evaluated: 0
Hard predictions: 11
Hard precision: 100.00%
Coverage: 84.62%
False positives, real labeled AI: 0
False negatives, AI labeled real: 0
Real abstentions: 2
AI abstentions: 0

| id | expected | label | score | outcome | source | notes |
|---|---:|---:|---:|---:|---|---|
| ai_cat_portrait | ai | likely_ai | 0.866 | correct | Pollinations generated image endpoint | Photorealistic animal portrait; generated test case from previous diagnostic run. |
| ai_gray_cat_closeup | ai | likely_ai | 0.834 | correct | Pollinations generated image endpoint | Photorealistic animal close-up; generated test case from previous diagnostic run. |
| ai_mountain_lake | ai | likely_ai | 0.859 | correct | Pollinations generated image endpoint | Photorealistic landscape; generated test case from previous diagnostic run. |
| real_dog | real | likely_not_ai | 0.121 | correct | https://unsplash.com/photos/8wTPqxlnKM4 | Real animal photo; used to watch false AI accusations. |
| real_cat_like_animal | real | uncertain | 0.702 | abstained | https://unsplash.com/photos/U5rMrSI7Pn4 | Real animal photo previously abstained due to high model AI score; important false-positive guard. |
| real_landscape_mountain | real | likely_not_ai | 0.100 | correct | https://unsplash.com/photos/-oWyJoSqBRM | Real mountain landscape photo. |
| real_city | real | uncertain | 0.688 | abstained | https://unsplash.com/photos/7BjmDICVloE | Real city photo previously abstained due to high model AI score; important false-positive guard. |
| real_people | real | likely_not_ai | 0.148 | correct | https://unsplash.com/photos/LyeduBb2Auk | Real people/scene photo. |
| real_food_table | real | likely_not_ai | 0.101 | correct | https://unsplash.com/photos/OJJIaFZOeX4 | Real food/table stock-like photo. |
| real_nature | real | likely_not_ai | 0.103 | correct | https://unsplash.com/photos/VB-w_3dnyvI | Real nature photo. |
| real_building | real | likely_not_ai | 0.102 | correct | https://unsplash.com/photos/mWRR1xj95hg | Real building/architecture photo. |
| real_vehicle | real | likely_not_ai | 0.103 | correct | https://unsplash.com/photos/sseiVD2XsOk | Real vehicle/transport photo. |
| real_landscape_water | real | likely_not_ai | 0.107 | correct | https://unsplash.com/photos/wpTWYBll4_w | Real water landscape photo. |

## Notes
- `ai_cat_portrait`: reasons=camera_metadata_present=make, model_ai_label=artificial:0.999, model_real_label=real:0.001, model_prediction=fake, model_margin=0.998, model_strong_ai_signal; warnings=none
- `ai_gray_cat_closeup`: reasons=camera_metadata_present=make, model_ai_label=artificial:0.997, model_real_label=real:0.003, model_prediction=fake, model_margin=0.994, model_strong_ai_signal; warnings=none
- `ai_mountain_lake`: reasons=camera_metadata_present=make, model_ai_label=artificial:0.999, model_real_label=real:0.001, model_prediction=fake, model_margin=0.997, model_strong_ai_signal; warnings=none
- `real_dog`: reasons=model_real_label=real:0.979, model_ai_label=artificial:0.021, model_prediction=real, model_margin=0.959, model_strong_real_signal; warnings=camera_metadata_missing_not_proof
- `real_cat_like_animal`: reasons=model_ai_label=artificial:0.975, model_real_label=real:0.025, model_prediction=fake, model_margin=0.949, model_strong_ai_signal; warnings=camera_metadata_missing_not_proof, model_strong_ai_signal_not_enough_without_metadata, ai_image_detection_not_definitive
- `real_landscape_mountain`: reasons=model_real_label=real:1.000, model_ai_label=artificial:0.000, model_prediction=real, model_margin=0.999, model_strong_real_signal; warnings=camera_metadata_missing_not_proof
- `real_city`: reasons=model_ai_label=artificial:0.955, model_real_label=real:0.045, model_prediction=fake, model_margin=0.909, model_strong_ai_signal; warnings=camera_metadata_missing_not_proof, model_strong_ai_signal_not_enough_without_metadata, ai_image_detection_not_definitive
- `real_people`: reasons=model_real_label=real:0.952, model_ai_label=artificial:0.048, model_prediction=real, model_margin=0.905, model_strong_real_signal; warnings=camera_metadata_missing_not_proof
- `real_food_table`: reasons=model_real_label=real:0.999, model_ai_label=artificial:0.001, model_prediction=real, model_margin=0.999, model_strong_real_signal; warnings=camera_metadata_missing_not_proof
- `real_nature`: reasons=model_real_label=real:0.996, model_ai_label=artificial:0.004, model_prediction=real, model_margin=0.993, model_strong_real_signal; warnings=camera_metadata_missing_not_proof
- `real_building`: reasons=model_real_label=real:0.998, model_ai_label=artificial:0.002, model_prediction=real, model_margin=0.997, model_strong_real_signal; warnings=camera_metadata_missing_not_proof
- `real_vehicle`: reasons=model_real_label=real:0.997, model_ai_label=artificial:0.003, model_prediction=real, model_margin=0.994, model_strong_real_signal; warnings=camera_metadata_missing_not_proof
- `real_landscape_water`: reasons=model_real_label=real:0.993, model_ai_label=artificial:0.007, model_prediction=real, model_margin=0.986, model_strong_real_signal; warnings=camera_metadata_missing_not_proof
