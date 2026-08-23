# Rakshak AI evaluation

`labels.json` contains manually reviewed incident time ranges. Keep calibration,
validation, and final test videos separate. Never tune thresholds on the final
test split. Report accuracy, precision, recall, F1, false alerts per hour, and
detection latency. A production claim requires substantially more independent
normal and incident footage than the five included development videos.

For weapon training, place YOLO images and labels under
`datasets/weapons/{images,labels}/{train,val,test}` and run `python train.py` on
a CUDA GPU. Promote `runs/detect/rakshak_custom_model/weights/best.pt` only if
the held-out test split improves both recall and false-positive rate.
