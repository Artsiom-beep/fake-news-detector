# AI Image Detector Eval

Run ID: `20260507_fulltest_image_metadata_only`
Dataset: `data\image_eval\v1\manifest.jsonl`
Model: `disabled`

Sources:
- AI-generated images and real images are listed in the versioned manifest.
- False `likely_ai` labels on real images are tracked separately because they are the highest-risk failure mode.

Manifest cases: 13
Evaluated cases: 13
Not evaluated: 0
Hard predictions: 0
Hard precision: 0.00%
Coverage: 0.00%
False positives, real labeled AI: 0
False negatives, AI labeled real: 0
Real abstentions: 10
AI abstentions: 3

| id | expected | label | score | outcome | source | notes |
|---|---:|---:|---:|---:|---|---|
| ai_cat_portrait | ai | uncertain | 0.040 | abstained | Pollinations generated image endpoint | Photorealistic animal portrait; generated test case from previous diagnostic run. |
| ai_gray_cat_closeup | ai | uncertain | 0.040 | abstained | Pollinations generated image endpoint | Photorealistic animal close-up; generated test case from previous diagnostic run. |
| ai_mountain_lake | ai | uncertain | 0.040 | abstained | Pollinations generated image endpoint | Photorealistic landscape; generated test case from previous diagnostic run. |
| real_dog | real | uncertain | 0.260 | abstained | https://unsplash.com/photos/8wTPqxlnKM4 | Real animal photo; used to watch false AI accusations. |
| real_cat_like_animal | real | uncertain | 0.260 | abstained | https://unsplash.com/photos/U5rMrSI7Pn4 | Real animal photo previously abstained due to high model AI score; important false-positive guard. |
| real_landscape_mountain | real | uncertain | 0.260 | abstained | https://unsplash.com/photos/-oWyJoSqBRM | Real mountain landscape photo. |
| real_city | real | uncertain | 0.260 | abstained | https://unsplash.com/photos/7BjmDICVloE | Real city photo previously abstained due to high model AI score; important false-positive guard. |
| real_people | real | uncertain | 0.260 | abstained | https://unsplash.com/photos/LyeduBb2Auk | Real people/scene photo. |
| real_food_table | real | uncertain | 0.260 | abstained | https://unsplash.com/photos/OJJIaFZOeX4 | Real food/table stock-like photo. |
| real_nature | real | uncertain | 0.260 | abstained | https://unsplash.com/photos/VB-w_3dnyvI | Real nature photo. |
| real_building | real | uncertain | 0.260 | abstained | https://unsplash.com/photos/mWRR1xj95hg | Real building/architecture photo. |
| real_vehicle | real | uncertain | 0.260 | abstained | https://unsplash.com/photos/sseiVD2XsOk | Real vehicle/transport photo. |
| real_landscape_water | real | uncertain | 0.260 | abstained | https://unsplash.com/photos/wpTWYBll4_w | Real water landscape photo. |

## Notes
- `ai_cat_portrait`: reasons=camera_metadata_present=make, optional_ai_image_model_disabled; warnings=ai_image_detection_not_definitive
- `ai_gray_cat_closeup`: reasons=camera_metadata_present=make, optional_ai_image_model_disabled; warnings=ai_image_detection_not_definitive
- `ai_mountain_lake`: reasons=camera_metadata_present=make, optional_ai_image_model_disabled; warnings=ai_image_detection_not_definitive
- `real_dog`: reasons=optional_ai_image_model_disabled; warnings=camera_metadata_missing_not_proof, ai_image_detection_not_definitive
- `real_cat_like_animal`: reasons=optional_ai_image_model_disabled; warnings=camera_metadata_missing_not_proof, ai_image_detection_not_definitive
- `real_landscape_mountain`: reasons=optional_ai_image_model_disabled; warnings=camera_metadata_missing_not_proof, ai_image_detection_not_definitive
- `real_city`: reasons=optional_ai_image_model_disabled; warnings=camera_metadata_missing_not_proof, ai_image_detection_not_definitive
- `real_people`: reasons=optional_ai_image_model_disabled; warnings=camera_metadata_missing_not_proof, ai_image_detection_not_definitive
- `real_food_table`: reasons=optional_ai_image_model_disabled; warnings=camera_metadata_missing_not_proof, ai_image_detection_not_definitive
- `real_nature`: reasons=optional_ai_image_model_disabled; warnings=camera_metadata_missing_not_proof, ai_image_detection_not_definitive
- `real_building`: reasons=optional_ai_image_model_disabled; warnings=camera_metadata_missing_not_proof, ai_image_detection_not_definitive
- `real_vehicle`: reasons=optional_ai_image_model_disabled; warnings=camera_metadata_missing_not_proof, ai_image_detection_not_definitive
- `real_landscape_water`: reasons=optional_ai_image_model_disabled; warnings=camera_metadata_missing_not_proof, ai_image_detection_not_definitive
