import os, subprocess
from subprocess import PIPE
from flask import Flask, render_template, request, redirect, flash, url_for, send_from_directory, Markup
from werkzeug.utils import secure_filename
import multiprocessing, threading
import re, random, string, shutil

app = Flask(__name__)

app.config['SECRET_KEY'] = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10)) # put in external file in prod

app.config['table'] = os.getcwd() + "/upload/table/"
app.config['data'] = os.getcwd() + "/upload/data/"
app.config['models'] = os.getcwd() + "/upload/models/"
app.config['feature_path'] = os.getcwd() + "/temp/"
app.config['output'] = os.getcwd() + "/out/"
app.config['code'] = os.getcwd() + "/4D-microscopy-pipeline/scripts/" 
app.config['fiji'] = os.getcwd() + "/Fiji.app/ImageJ-linux64"
app.config['progress'] = os.getcwd() + "/progress/"

app.config['MAX_CORES'] =  str(multiprocessing.cpu_count())
app.config['STACKPREFIX'] =  "_"
app.config['STACKSUFFIX'] =  "up"
app.config['PREFIX'] =  "''"
app.config['UNIT'] =  "nm"
app.config['IMAGE_STACK_NAME'] = "image_"

########################################################################
# Helper Functions
#######################################################################

def get_save_features(feature_model_table,image,modelname,xy_,z_,adjusted_intensity,crop):
    '''
    Performs Step 1a, generating and wriitng featiures to disk. Makes shell call to Fiji. 

    Parameters are parsed in the form submitted to the index route

    '''
    os.system(app.config['fiji'] + ' --ij2 --headless --run ' + app.config['code']+'generate_save_features.groovy '
    + '\'feature_model_table="'+feature_model_table+'",\'' + '\'imageStackLocation="'+app.config['data']+'",\'' + 
    '\'imageStackName="'+image[:image.find('.')]+'",\'' + '\'modelName="'+modelname+'",\'' + '\'featureSavePath="'+app.config['feature_path']+'",\''
    + '\'numberThreadsToUse="'+app.config['MAX_CORES']+'",\'' + '\'pixelSize_xy="'+xy_+'",\'' + '\'pixelSize_z="'+z_+'",\'' +
    '\'intensityScalingFactor="'+adjusted_intensity+'",\'' + '\'cropBox="'+crop+'"\' > '+app.config['progress']+image[:image.find('.')]+".txt")

    # reset progress and progress with the pipline
    for file in os.listdir(app.config['progress']):
        os.remove(app.config['progress'] + file)

def apply_classifer(feature_model_table,real_names,count,modelname,xy_,z_,channels,image):
    '''
    Performs Step 1b, apply a .model classifer to image stack. Makes shell call to Fiji

    Parameters are parsed in the form submitted to the index route

    '''
    os.system(app.config['fiji'] + ' --ij2 --headless --run ' + app.config['code']+'apply_classifiers.groovy '
    + '\'feature_model_table="'+feature_model_table+'",\'' + '\'imageStackName="'+real_names[count][:real_names[count].find('.')]+'",\'' 
    + '\'featurePath="'+app.config['feature_path']+'",\'' + '\'modelPath="'+app.config['models']+'",\'' + '\'modelName="'+modelname+'",\''  
    + '\'savePath="'+app.config['output']+'",\'' + '\'numberThreadsToUse="'+app.config['MAX_CORES']+'",\'' 
    + '\'pixelSize_unit="'+app.config['UNIT']+'",\'' + '\'pixelSize_xy="'+xy_+'",\'' + '\'pixelSize_z="'+z_+'",\'' + '\'channels="'+channels+'"\' > ' + app.config['progress']+image[:image.find('.')]+".txt")
    
    # reset progress and progress with the pipline
    for file in os.listdir(app.config['progress']):
        os.remove(app.config['progress'] + file)

def segment(feature_model_table,modelname,xy_,z_,crop,real_names,channels,ISF,ISFT):
    '''
    Perform steps 1 and 2. To be called as a background process. Parameters are parsed in the form submitted to the index route.
    All server site parameter validation to occur before calling this process.

    '''
    for count, image in enumerate(os.listdir(app.config['data'])):
        # Adjusted Intensity Scaling Factor 
        adjusted_intensity = str(float(ISF) * (float(ISFT) **  count))

        get_save_features(feature_model_table,image,modelname,xy_,z_,adjusted_intensity,crop)
        apply_classifer(feature_model_table,real_names,count,modelname,xy_,z_,channels,image)

        print(str(count), "compeleted")
    
    reset()

def reset():
    '''
    helper to delete client uplaods and reset before handling the next request
    '''
    # clear directorys
    for dir in ['table', 'models', 'data']:
        for file in os.listdir(app.config[dir]):
            os.remove(app.config[dir]+file)

    # delete features, never run base app with admin privelledges just in case
    for dir in os.listdir(app.config['feature_path']):
        shutil.rmtree(app.config['feature_path']+dir, ignore_errors=False, onerror=None)

def check_busy():
    '''
    returns True if LLAMAnating in progress
    '''
    return True if (len(os.listdir(app.config["progress"])) == 1) else False

def getImages():
    '''
    Returns list[str,] of URLS for generated images located in /output/
    '''
    tiffs = []
    for file in os.listdir(app.config['output']+"segmented/"):
        tiffs.append("out/segmented/"+file)

    for file in os.listdir(app.config['output']+"probability_maps/"):
        tiffs.append("out/probability_maps/"+file)
    
    return tiffs


########################################################################
# Application / Routing logic
#######################################################################



@app.route("/", methods=['POST','GET'])
def index():
    '''
    Main landing Page for LLAMA (Currently just step 1)

    Logic:

    GET:
    - Show Form to the user to submit new request if not currently working on a request otherwise redirect to that progress page

    POST:
    - Validate form data, create calls to Fiji to start LLAMA processes running in the background. Redirect to progress page OR error if unsuccessful

    '''

    # only work on a single request at a time
    if check_busy():
        redirect(url_for('output'))

    if request.method == 'GET':
        return render_template('index.html', images=getImages())
    
    else:

        # Process form data

        # Feature Model Table
        feature_model_table = request.files['FMT']
        filename_secure = secure_filename(feature_model_table.filename)

        if filename_secure == '':
            flash('Please upload a file')
            return redirect(url_for('index'))

        if not filename_secure.endswith(".txt"):
            flash('Feature Model Table must be a text file')
            return redirect(url_for('index'))        

        feature_model_table.save(os.path.join(app.config['table'], filename_secure))


        # Weka Model
        Weka_model = request.files['model']
        filename_secure = secure_filename(Weka_model.filename)

        if filename_secure == '':
            flash('Please upload a file')
            return redirect(url_for('index'))

        if not filename_secure.endswith(".model"):
            flash('Weka model must be a .model file')
            return redirect(url_for('index'))        

        Weka_model.save(os.path.join(app.config['models'], filename_secure))
        
        modelname = filename_secure[:-6] # modelname

        # Image stack
        image_files = request.files.getlist("stack")

        if len(image_files) == 0:
            flash('Please upload at least one image stack to segment')
            return redirect(url_for('index'))


        for stack in image_files:
            # check first
            filename_secure = secure_filename(stack.filename)

            if filename_secure == '':
                flash('Image names cannot be empty')
                return redirect(url_for('index'))

            if not (filename_secure.endswith(".tiff") or filename_secure.endswith(".tif")):
                flash('Image stacks must be in the format .tiff or .tif')
                return redirect(url_for('index'))        
            
        real_names = [] # for output only

        for count, stack in enumerate(image_files):
            # save
            stack.save(os.path.join(app.config['data'], app.config['IMAGE_STACK_NAME'] + str(count) + "upload.tif"))
            real_names.append(secure_filename(stack.filename))

        # Prob maps
        if request.form.get('probmap'):
            probmaps = 'true'
        else:
            probmaps = 'false'

        # Pixel size            

        xy_ = request.form.get('xy')
        z_ = request.form.get('z')
        
        # Advanced
        ISF = request.form.get('ISF')
        ISFT = request.form.get('ISFT')

        # Crop
        crop = request.form.get('crop')

        # Groups
        groups = request.form.get('group')
        
        formatGroup = []
        temp = []
        for char in groups:
            if char == ",":
                if temp != []:
                    formatGroup.append(temp)
                temp = []
            else:
                temp.append(int(char))
        if temp != []:
            formatGroup.append(temp)

        groups = formatGroup
        
        # channels
        channels = request.form.get('channels')

        # FORMAT

        feature_model_table = app.config['table']+os.listdir(app.config['table'])[0]
        
        # (Do LLAMA step 1) Save features to disk // apply classifer
        try:
            MVG_thread = threading.Thread(target=segment, name="segment", 
            args=(feature_model_table,modelname,xy_,z_,crop,real_names,channels,ISF,ISFT,))
            MVG_thread.start()
        except:
            reset()
            flash('Something went wrong. Please try again.')
            return redirect(url_for('index'))

        return render_template('output.html')
        
        
@app.route("/output/", methods=['GET'])
def output():
    '''
    Route to display progress to the user. Redirects to index if not currently running. 

    Logic:

    - If file in progress folder, background process must be running. Show contents of this file to the user.
    - TODO: Rather than display all the output, summarise to key stages (eg generating features, performing sgmenetion, saving to file, ..)
    '''
    
    if check_busy():
        with open(app.config["progress"] + os.listdir(app.config["progress"])[0]) as f:
            prog = f.readlines()
        f.close()

        p_markup = ''
        for p in prog:
            p_markup += str(p.replace('\n', '<br>'))

        progForUser = Markup('<h4 class="background"> '+p_markup +'</h4>')
        return render_template('output.html', progress=progForUser)
    
    else:
        return redirect(url_for('index'))


@app.route("/out/segmented/<filename>", methods=['GET'])
def out_s(filename):
    try:
        return send_from_directory(app.config["output"]+"/segmented/", filename=filename, as_attachment=True)
    except FileNotFoundError:
        abort(404)

@app.route("/out/probability_maps/<filename>", methods=['GET'])
def out_pb(filename):
    try:
        return send_from_directory(app.config["output"]+"/probability_maps/", filename=filename, as_attachment=True)
    except FileNotFoundError:
        abort(404)

if __name__ == "__main__":
    # change before prod
    app.run(host='0.0.0.0', port=5000, debug=True)

