import hashlib,json
import numpy as np
import sklearn
from sklearn.tree import DecisionTreeClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import f1_score,confusion_matrix
LEVELS=['low','medium','high']
# 模型口径版本：训练数据、参数或特征一旦调整，必须换版本，旧记录不得用新版补算。
MODEL_VERSION='dt-v1'
FEATURES=(('humidity','含水率','%'),('holes','虫孔数',''),('mold','霉面积','%'))

def _fit():
    rng=np.random.default_rng(31)
    x=np.column_stack([rng.uniform(30,90,600),rng.integers(0,31,600),rng.uniform(0,25,600)])
    # 专家规则构造的合成训练样本，不能替代真实馆藏外部验证。
    y=np.where((x[:,0]>=72)|(x[:,2]>=10),'high',np.where((x[:,0]>=60)|(x[:,1]>=10)|(x[:,2]>=2),'medium','low'))
    train,test=train_test_split(np.arange(len(x)),test_size=.25,random_state=31,stratify=y)
    model=DecisionTreeClassifier(max_depth=5,min_samples_leaf=4,random_state=31).fit(x[train],y[train])
    return model,x,y,train,test

def _fingerprint(model,dataset_sha):
    tree=model.tree_
    h=hashlib.sha256()
    h.update(json.dumps({'version':MODEL_VERSION,'dataset':dataset_sha,'max_depth':model.max_depth,'min_samples_leaf':model.min_samples_leaf,'random_state':model.random_state,'sklearn':sklearn.__version__,'classes':[str(c) for c in model.classes_]},ensure_ascii=False,sort_keys=True).encode())
    h.update(np.asarray(tree.children_left,dtype=np.int64).tobytes())
    h.update(np.asarray(tree.children_right,dtype=np.int64).tobytes())
    h.update(np.asarray(tree.feature,dtype=np.int64).tobytes())
    h.update(np.asarray(tree.threshold,dtype=np.float64).tobytes())
    h.update(np.asarray(tree.value,dtype=np.float64).tobytes())
    return h.hexdigest()

def explain(humidity,holes,mold):
    model,x,y,train,test=_fit()
    dataset_sha=hashlib.sha256(x.tobytes()+y.tobytes()).hexdigest()
    fingerprint=_fingerprint(model,dataset_sha)
    sample=np.array([[float(humidity),float(holes),float(mold)]],dtype=float)
    predicted=str(model.predict(sample)[0])
    tree=model.tree_
    path=[]
    for node in model.decision_path(sample)[0].indices:
        node=int(node)
        if tree.feature[node]>=0:
            key,label,unit=FEATURES[int(tree.feature[node])]
            threshold=float(tree.threshold[node])
            value=float(sample[0,int(tree.feature[node])])
            left=value<=threshold
            path.append({'node':node,'feature':key,'label':label,'unit':unit,'value':value,'threshold':threshold,'branch':'left' if left else 'right','operator':'<=' if left else '>'})
        else:
            counts=np.asarray(tree.value[node][0],dtype=float)
            total=float(counts.sum())
            distribution={LEVELS[i]:round(float(counts[i])/total,4) if total else 0.0 for i in range(len(LEVELS))}
            path.append({'node':node,'leaf':True,'prediction':str(model.classes_[int(np.argmax(counts))]),'distribution':distribution})
    prediction=model.predict(x[test])
    metrics={'macro_f1':float(f1_score(y[test],prediction,average='macro')),'confusion_matrix':confusion_matrix(y[test],prediction,labels=LEVELS).tolist(),'labels':LEVELS,'train_count':len(train),'test_count':len(test),'seed':31,'dataset_sha256':dataset_sha,'model_version':MODEL_VERSION,'model_fingerprint':fingerprint,'data_source':'专家规则合成样本；留出指标仅证明内部可复现性'}
    return {'predicted':predicted,'metrics':metrics,'decision_path':path,'input':{'humidity':float(humidity),'holes':int(holes),'mold':float(mold)},'model':{'version':MODEL_VERSION,'fingerprint':fingerprint,'dataset_sha256':dataset_sha,'seed':31,'max_depth':model.max_depth,'min_samples_leaf':model.min_samples_leaf,'sklearn':sklearn.__version__}}

def classify(humidity,holes,mold):
    result=explain(humidity,holes,mold)
    return result['predicted'],result['metrics']
