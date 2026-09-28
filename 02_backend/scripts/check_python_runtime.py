"""Fresh-process ML/data/OCR compatibility gate used before AMP generation."""
import argparse
import importlib
import sys


def check(ocr=False):
    print('Checking Python runtime:', sys.executable, flush=True)
    names = ['numpy', 'pandas', 'scipy', 'sklearn', 'xgboost', 'pyarrow', 'lancedb']
    if ocr:
        names += ['cv2', 'onnxruntime', 'fitz', 'PIL', 'rapidocr_onnxruntime']
    modules = {}
    for name in names:
        module = importlib.import_module(name)
        modules[name] = module
        print(f"  {name}: {getattr(module, '__version__', 'imported')} ({module.__file__})", flush=True)
    np, pd = modules['numpy'], modules['pandas']
    frame = pd.DataFrame(np.array([[0., 1.], [1., 0.], [0., 2.], [2., 0.]]), columns=['a', 'b'])
    assert modules['pyarrow'].Table.from_pandas(frame).to_pandas().equals(frame)
    from sklearn.tree import DecisionTreeClassifier
    labels = np.array([0, 1, 0, 1])
    DecisionTreeClassifier(max_depth=1).fit(frame, labels).predict(frame)
    modules['xgboost'].XGBClassifier(n_estimators=2, max_depth=1, n_jobs=1).fit(frame, labels).predict(frame)
    if ocr:
        modules['cv2'].cvtColor(np.zeros((8, 8, 3), dtype=np.uint8), modules['cv2'].COLOR_BGR2GRAY)
        modules['rapidocr_onnxruntime'].RapidOCR(intra_op_num_threads=2, inter_op_num_threads=2)
    print('Python data/ML' + ('/OCR' if ocr else '') + ' runtime ready.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ocr', action='store_true')
    args = parser.parse_args()
    try:
        check(args.ocr)
    except Exception:
        print('Runtime validation failed. Repair dependencies with 01_installer/install.py, '
              'then start a fresh CML session before running generation/features/training.', file=sys.stderr)
        raise


if __name__ == '__main__':
    main()
